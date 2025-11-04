
import streamlit as st
import requests
import json
import os
import pandas as pd
from databricks.sdk import WorkspaceClient

# --- Page Configuration ---
st.set_page_config(
    page_title="medtech-patient-app",
    page_icon="🏥",
    layout="wide"
)

# --- Configuration ---
# Hardcoded for Databricks Apps deployment
CHAT_ENDPOINT_NAME = 'mas-ea2fbc2e-endpoint'
DATABRICKS_HOST = 'https://e2-demo-field-eng.cloud.databricks.com'
WAREHOUSE_ID = 'fd41d22f135b1170'  # SQL Warehouse ID

# --- Authentication Setup ---
def get_auth_headers():
    """Get authentication headers for API calls"""
    try:
        w = WorkspaceClient()
        token = w.config.token
        if token:
            return {'Authorization': f'Bearer {token}'}
    except:
        pass
    
    token = os.environ.get("DATABRICKS_TOKEN")
    if token:
        return {'Authorization': f'Bearer {token}'}
    
    client_id = os.environ.get("DATABRICKS_CLIENT_ID")
    client_secret = os.environ.get("DATABRICKS_CLIENT_SECRET")
    
    if client_id and client_secret:
        token_url = f"{DATABRICKS_HOST}/oidc/v1/token"
        response = requests.post(
            token_url,
            data={
                'grant_type': 'client_credentials',
                'scope': 'all-apis'
            },
            auth=(client_id, client_secret)
        )
        if response.status_code == 200:
            token = response.json()['access_token']
            return {'Authorization': f'Bearer {token}'}
    
    return {}

# --- SQL Execution ---
def execute_sql_query(sql_query, warehouse_id):
    """Execute SQL query using Databricks SQL Statement Execution API"""
    try:
        w = WorkspaceClient()
        
        # Execute the query
        result = w.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=sql_query,
            wait_timeout='30s'
        )
        
        # Extract data
        if result.result and result.result.data_array:
            columns = [col.name for col in result.manifest.schema.columns]
            data = result.result.data_array
            df = pd.DataFrame(data, columns=columns)
            return df
        else:
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Error executing SQL query: {str(e)}")
        return None

# ==============================================================================
# PATIENT PROFILER SECTION
# ==============================================================================
st.title("👤 Patient Profile")

# Initialize loaded patient ID in session state
if "loaded_patient_id" not in st.session_state:
    st.session_state.loaded_patient_id = None

# Patient ID input
patient_id = st.text_input("Enter Patient ID:")

# Load patient data when button is clicked
if st.button("Load Patient Data") and patient_id:
    st.session_state.loaded_patient_id = patient_id

# Display patient data if we have a loaded patient ID
if st.session_state.loaded_patient_id:
    loaded_patient_id = st.session_state.loaded_patient_id
    with st.spinner("Loading patient data..."):
        # First, get patient information
        patient_query = f"""
        SELECT 
            patient_id,
            device_id,
            region,
            patient_diagnosis,
            activation_date,
            birth_year,
            device_type
        FROM `morgancatalog`.`medtech_ldp_1`.`silver_patient_registry`
        WHERE patient_id = '{loaded_patient_id}'
        """
        
        patient_df = execute_sql_query(patient_query, WAREHOUSE_ID)
        
        if patient_df is not None and not patient_df.empty:
            # Display patient information
            st.subheader("Patient Information")
            
            patient_data = patient_df.iloc[0]
            
            # Display patient details in columns
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Patient ID", patient_data['patient_id'])
            with col2:
                st.metric("Device ID", patient_data['device_id'])
            with col3:
                st.metric("Birth Year", int(patient_data['birth_year']))
            with col4:
                st.metric("Region", patient_data['region'])
            
            col5, col6, col7 = st.columns(3)
            with col5:
                st.metric("Diagnosis", patient_data['patient_diagnosis'])
            with col6:
                st.metric("Device Type", patient_data['device_type'])
            with col7:
                activation = pd.to_datetime(patient_data['activation_date']).strftime('%Y-%m-%d')
                st.metric("Activation Date", activation)
            
            st.divider()
            
            # Now get glucose readings
            glucose_query = f"""
            SELECT
              CAST(t.reading_timestamp AS TIMESTAMP) AS reading_timestamp,
              AVG(t.glucose_value) AS avg_glucose_value
            FROM
              `morgancatalog`.`medtech_ldp_1`.`silver_device_telemetry_stream` t
                JOIN `morgancatalog`.`medtech_ldp_1`.`silver_patient_registry` p
                  ON t.device_id = p.device_id
            WHERE
              p.patient_id = '{loaded_patient_id}'
              AND t.reading_timestamp IS NOT NULL
              AND t.glucose_value IS NOT NULL
            GROUP BY
              t.reading_timestamp
            ORDER BY
              t.reading_timestamp
            """
            
            glucose_df = execute_sql_query(glucose_query, WAREHOUSE_ID)
            
            if glucose_df is not None and not glucose_df.empty:
                # Convert reading_timestamp to datetime
                glucose_df['reading_timestamp'] = pd.to_datetime(glucose_df['reading_timestamp'])
                glucose_df['avg_glucose_value'] = pd.to_numeric(glucose_df['avg_glucose_value'])
                
                # Display glucose metrics
                st.subheader("Glucose Monitoring")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Readings", len(glucose_df))
                with col2:
                    st.metric("Avg Glucose", f"{glucose_df['avg_glucose_value'].mean():.1f} mg/dL")
                with col3:
                    st.metric("Latest Reading", f"{glucose_df['avg_glucose_value'].iloc[-1]:.1f} mg/dL")
                
                # Plot line chart
                st.subheader("Glucose Readings Over Time")
                st.line_chart(glucose_df.set_index('reading_timestamp')['avg_glucose_value'])
                
                # Show data table
                with st.expander("View Raw Glucose Data"):
                    st.dataframe(glucose_df)
            else:
                st.warning(f"No glucose readings found for patient ID: {loaded_patient_id}")
                
        else:
            st.error(f"Patient ID '{loaded_patient_id}' not found in registry.")

# Add a divider
st.divider()

# ==============================================================================
# CHATBOT SECTION
# ==============================================================================
st.title("💬 MedTech Agent Chat")

# Initialize chat history in session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Initialize pending prompt in session state
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None

# Add a quick action button to ask about the current patient
if st.session_state.loaded_patient_id:
    if st.button(f"📋 Ask about Patient {st.session_state.loaded_patient_id}"):
        st.session_state.pending_prompt = f"Tell me about Patient {st.session_state.loaded_patient_id}"

# Display chat messages from history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Always show chat input
user_input = st.chat_input(f"Ask a question about Patient {st.session_state.loaded_patient_id if st.session_state.loaded_patient_id else 'data'}...")

# Check for pending prompt from button or new chat input
prompt = None
if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None
elif user_input:
    prompt = user_input

# Process the prompt
if prompt:
    # Display user message in chat message container
    st.chat_message("user").markdown(prompt)
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Add patient context if available
    if st.session_state.loaded_patient_id:
        context_prompt = f"Context: The user is currently viewing data for Patient ID: {st.session_state.loaded_patient_id}. {prompt}"
    else:
        context_prompt = prompt

    # Prepare the request payload with streaming enabled
    request_payload = {
        "input": [
            {
                "role": "user",
                "content": context_prompt
            }
        ],
        "stream": True  # Enable streaming
    }
    
    # Display assistant response in chat message container
    with st.chat_message("assistant"):
        try:
            # Get authentication headers
            headers = get_auth_headers()
            headers['Content-Type'] = 'application/json'
            headers['Accept'] = 'text/event-stream'  # For SSE
            
            # Build the endpoint URL
            endpoint_url = f"{DATABRICKS_HOST}/serving-endpoints/{CHAT_ENDPOINT_NAME}/invocations"
            
            # Make the streaming request
            response = requests.post(
                endpoint_url,
                headers=headers,
                json=request_payload,
                stream=True,  # Enable streaming
                timeout=60
            )
            
            if response.status_code == 200:
                full_response = ""
                placeholder = st.empty()
                
                # Track the final message ID we want to display
                final_message_id = None
                
                # Process the streaming response
                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode('utf-8')
                        
                        # SSE format: data: {json}
                        if decoded_line.startswith('data: '):
                            json_str = decoded_line[6:]  # Remove 'data: ' prefix
                            
                            if json_str == '[DONE]':
                                break
                            
                            try:
                                event = json.loads(json_str)
                                
                                # Handle streaming delta events
                                if event.get("type") == "response.output_text.delta":
                                    # Look for the final message stream (the one that starts with "Here is")
                                    item_id = event.get("item_id", "")
                                    delta_text = event.get("delta", "")
                                    
                                    # Check if this is the final response (contains the actual answer)
                                    if "run--" in item_id:
                                        final_message_id = item_id
                                        full_response += delta_text
                                        placeholder.markdown(full_response + "▌")
                                
                                # Handle completion events
                                elif event.get("type") == "response.output_item.done":
                                    item = event.get("item", {})
                                    # Only use the final message with the correct ID
                                    if item.get("id") == final_message_id and item.get("role") == "assistant":
                                        content = item.get("content", [])
                                        if isinstance(content, list) and len(content) > 0:
                                            for content_item in content:
                                                if content_item.get("type") == "output_text":
                                                    full_response = content_item.get("text", "")
                                                    placeholder.markdown(full_response)
                            
                            except json.JSONDecodeError:
                                continue
                
                # Final update without cursor
                if full_response:
                    placeholder.markdown(full_response)
                    st.session_state.messages.append({"role": "assistant", "content": full_response})
                else:
                    st.warning("No response received from the model.")
                
            else:
                st.error(f"Error {response.status_code}: {response.text}")
                    
        except Exception as e:
            st.error(f"Error calling endpoint: {str(e)}")
