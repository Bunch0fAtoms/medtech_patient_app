
import streamlit as st
import requests
import json
import os
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
DASHBOARD_ID = '01f0b5c1e452196687b984bdb1ff4f70'
DATABRICKS_HOST = 'https://e2-demo-field-eng.cloud.databricks.com'
WORKSPACE_ID = '1444828305810485'

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

# ==============================================================================
# DASHBOARD SECTION
# ==============================================================================
st.title("📊 MedTech Quality Management System Dashboard")

# Construct the correct embed URL with workspace ID
embed_url = f"{DATABRICKS_HOST}/embed/dashboardsv3/{DASHBOARD_ID}?o={WORKSPACE_ID}"

# Direct iframe embedding
st.components.v1.iframe(
    src=embed_url,
    width=None,
    height=600,
    scrolling=True
)

# Add a divider
st.divider()

# ==============================================================================
# CHATBOT SECTION
# ==============================================================================
st.title("💬 MedTech Agent Chat")

# Initialize chat history in session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages from history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# React to user input
if prompt := st.chat_input("Ask a question about your MedTech device data..."):
    # Display user message in chat message container
    st.chat_message("user").markdown(prompt)
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Prepare the request payload with streaming enabled
    request_payload = {
        "input": [
            {
                "role": "user",
                "content": prompt
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
