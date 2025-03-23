import streamlit as st
import boto3
import pandas as pd
import json
import time
import os
from io import StringIO
from datetime import datetime
import re

# Set up page config
st.set_page_config(
    page_title="1Shot Email Marketing",
    page_icon="🎯",
    layout="wide"
)

# Custom CSS for better appearance, inspired by Data Synth UI
st.markdown("""
<style>
    /* Global colors and styles */
    :root {
        --primary-color: #FF6B6B;
        --secondary-color: #4ECDC4;
        --dark-bg: #292D3E;
        --light-text: #F7FFF7;
        --highlight: #FFE66D;
    }
    
    /* Main layout */
    .main {
        background-color: var(--dark-bg);
    }
    
    /* Sidebar styling */
    .css-1d391kg {
        background-color: var(--dark-bg);
    }
    
    /* Text colors */
    h1, h2, h3, h4, h5, h6 {
        color: var(--primary-color) !important;
    }
    
    p, li, label, div {
        color: var(--light-text) !important;
    }
    
    /* App name and logo styling */
    .app-header {
        display: flex;
        align-items: center;
        margin-bottom: 2rem;
    }
    
    .app-logo {
        font-size: 2.5rem;
        color: var(--primary-color) !important;
        font-weight: bold;
        margin-right: 0.5rem;
    }
    
    .app-name {
        font-size: 2.5rem;
        color: var(--secondary-color) !important;
        font-weight: bold;
    }
    
    /* Box styles */
    .content-box {
        background-color: rgba(255, 255, 255, 0.05);
        border-radius: 0.5rem;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
    }
    
    .info-box {
        padding: 1rem;
        background-color: rgba(78, 205, 196, 0.1);
        border-radius: 0.5rem;
        border-left: 0.5rem solid #4ECDC4;
        margin-bottom: 1rem;
    }
    
    .success-box {
        padding: 1rem;
        background-color: rgba(78, 205, 196, 0.2);
        border-radius: 0.5rem;
        border-left: 0.5rem solid #4ECDC4;
        margin-bottom: 1rem;
    }
    
    .warning-box {
        padding: 1rem;
        background-color: rgba(255, 230, 109, 0.2);
        border-radius: 0.5rem;
        border-left: 0.5rem solid #FFE66D;
        margin-bottom: 1rem;
    }
    
    /* Button styling */
    .stButton > button {
        background-color: var(--primary-color);
        color: white;
        border: none;
        border-radius: 0.3rem;
        padding: 0.5rem 1rem;
        font-weight: bold;
    }
    
    .stButton > button:hover {
        background-color: #ff8585;
    }
    
    /* Input fields */
    .stTextInput > div > div > input {
        background-color: rgba(255, 255, 255, 0.1);
        color: white;
        border-radius: 0.3rem;
    }
    
    /* Table styles */
    .dataframe {
        color: var(--light-text) !important;
    }
    
    .dataframe th {
        background-color: var(--primary-color) !important;
        color: white !important;
    }
    
    .dataframe td {
        background-color: rgba(255, 255, 255, 0.05) !important;
    }
    
    /* Chat container */
    .chat-container {
        height: 400px;
        overflow-y: scroll;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 0.5rem;
        padding: 1rem;
        margin-bottom: 1rem;
        background-color: rgba(255, 255, 255, 0.05);
    }
    
    /* Chat message styles */
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
        display: flex;
    }
    
    .chat-message.user {
        background-color: rgba(255, 107, 107, 0.2);
    }
    
    .chat-message.assistant {
        background-color: rgba(78, 205, 196, 0.2);
    }
    
    .chat-message .avatar {
        width: 10%;
        display: flex;
        justify-content: center;
        align-items: flex-start;
    }
    
    .chat-message .content {
        width: 90%;
    }
    
    /* Email preview */
    .email-preview {
        border: 1px solid rgba(255, 255, 255, 0.2);
        padding: 1.5rem;
        border-radius: 0.5rem;
        background-color: rgba(255, 255, 255, 0.05);
        margin-bottom: 1.5rem;
    }
    
    /* Target icon in sidebar */
    .target-icon {
        font-size: 50px;
        color: var(--primary-color);
        text-align: center;
        margin-bottom: 20px;
    }
    
    /* Selected section highlight */
    .selected-section {
        background-color: rgba(255, 107, 107, 0.2);
        padding: 0.5rem;
        border-radius: 0.3rem;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state variables
if 'selected_flights' not in st.session_state:
    st.session_state.selected_flights = []

if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

if 'email_templates' not in st.session_state:
    st.session_state.email_templates = {}

if 'active_section' not in st.session_state:
    st.session_state.active_section = "flights"

if 'segments_loaded' not in st.session_state:
    st.session_state.segments_loaded = False

if 'template_uploaded' not in st.session_state:
    st.session_state.template_uploaded = False

# Initialize next_input for handling suggestions
if 'next_input' not in st.session_state:
    st.session_state.next_input = ""

# Configuration - modify these for your environment
BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'knowledgebase-bedrock-agent-ab3')
AGENT_ID = os.environ.get('AGENT_ID', '')
AGENT_ALIAS_ID = os.environ.get('AGENT_ALIAS_ID', 'TSTALIASID')
ITEMS_CSV_PATH = 'data/travel_items.csv'
USERS_CSV_PATH = 'data/travel_users.csv'
SEGMENTS_OUTPUT_PATH = 'segments/batch_segment_input_ab3.json.out'
EMAIL_TEMPLATES_PATH = 'email_templates/'

# Helper functions
@st.cache_resource
def get_aws_clients():
    try:
        # Initialize AWS clients with proper credentials
        s3_client = boto3.client('s3')
        
        bedrock_regions = boto3.Session().get_available_regions('bedrock-agent-runtime')
        current_region = boto3.Session().region_name
        bedrock_region = current_region if current_region in bedrock_regions else 'us-east-1'
        
        bedrock_agent_client = boto3.client(
            'bedrock-agent-runtime',
            region_name=bedrock_region
        )
        
        return s3_client, bedrock_agent_client
    except Exception as e:
        st.error(f"Error initializing AWS clients: {str(e)}")
        return None, None

def read_s3_csv(bucket, key):
    """Read CSV data from S3"""
    try:
        s3_client, _ = get_aws_clients()
        if not s3_client:
            return None
            
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        df = pd.read_csv(StringIO(content))
        return df
    except Exception as e:
        st.error(f"Error reading CSV from S3: {str(e)}")
        return None

def read_s3_json(bucket, key):
    """Read JSONL data from S3"""
    try:
        s3_client, _ = get_aws_clients()
        if not s3_client:
            return None
            
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        json_objects = []
        for line in content.strip().split('\n'):
            if line:  # Skip empty lines
                json_objects.append(json.loads(line))
        return json_objects
    except Exception as e:
        st.error(f"Error reading JSON from S3: {str(e)}")
        return None

def write_to_s3(bucket, key, content):
    """Write content to S3"""
    try:
        s3_client, _ = get_aws_clients()
        if not s3_client:
            return False
            
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content
        )
        return True
    except Exception as e:
        st.error(f"Error writing to S3: {str(e)}")
        return False

def extract_email_content(response_text):
    """Extract email subject and body from agent response"""
    email_content = {
        "subject": "",
        "body": ""
    }
    
    # Try to find "Subject:" line
    subject_match = re.search(r'Subject:(.*?)(?:\n\n|\r\n\r\n)', response_text, re.IGNORECASE | re.DOTALL)
    if subject_match:
        email_content["subject"] = subject_match.group(1).strip()
        
        # Extract body (everything after the subject and first blank line)
        body_parts = response_text.split(subject_match.group(0), 1)
        if len(body_parts) > 1:
            email_content["body"] = body_parts[1].strip()
    else:
        # If no clear subject line, look for patterns
        lines = response_text.strip().split('\n')
        for i, line in enumerate(lines):
            if "subject:" in line.lower():
                email_content["subject"] = line.split(":", 1)[1].strip()
                if i+1 < len(lines):
                    email_content["body"] = '\n'.join(lines[i+2:]).strip()
                break
    
    # If still no clear subject found, make a best guess
    if not email_content["subject"] and lines:
        email_content["subject"] = lines[0].strip()
        if len(lines) > 1:
            email_content["body"] = '\n'.join(lines[1:]).strip()
    
    return email_content

def create_segment_json(flight_ids):
    """Create JSON for batch segment job"""
    lines = []
    for flight_id in flight_ids:
        lines.append(json.dumps({"itemId": flight_id}))
    return "\n".join(lines)

def invoke_agent(prompt, session_id=None):
    """Invoke the Bedrock Agent with a prompt and return the response"""
    if not session_id:
        session_id = f"session-{int(time.time())}"
    
    _, bedrock_agent_client = get_aws_clients()
    
    # If agent client is not available or AGENT_ID is not set, use mock response
    if not bedrock_agent_client or not AGENT_ID:
        # For demonstration purposes only
        time.sleep(2)  # Simulate API call delay
        
        # Simple mock response
        if "generate email" in prompt.lower() or "email template" in prompt.lower():
            return """
Based on the flight details:
- Source: Singapore
- Destination: Hong Kong
- Month: October
- Airline: PandaPaw Express

Here's a suggested email template:

Subject: Exclusive October Offer: Singapore to Hong Kong with PandaPaw Express

Dear Valued Traveler,

We're excited to offer you an exclusive opportunity to explore the vibrant city of Hong Kong this October!

✈️ Singapore to Hong Kong
🗓️ Travel Period: October 2023
💰 Special Price: $5,200 (20% discount for members!)
⭐ Duration: 10 days
🛫 Airline: PandaPaw Express

During your stay, you might enjoy:
• Experiencing the breathtaking view from Victoria Peak
• Exploring the bustling markets of Mong Kok
• Taking the iconic Star Ferry across Victoria Harbour
• Savoring authentic dim sum at local restaurants
• Visiting the Big Buddha on Lantau Island

Book now at https://wanderly.travel/booking and use promo code 74000 to secure this special offer!

Best regards,
The Wanderly Team
"""
        elif "list" in prompt.lower() and "flight" in prompt.lower():
            return """
Here are the promotional flights available:

1. Singapore to Hong Kong (PandaPaw Express, October, $5,200)
   - 10-day trip
   - Has user segment: Yes (149 users)
   
2. Tokyo to Paris (KoalaHug Express, November, $7,800)
   - 14-day trip
   - Has user segment: Yes (150 users)
   
3. Hong Kong to London (ButterflyWing Express, December, $6,500)
   - 7-day trip
   - Has user segment: Yes (150 users)

To generate an email template for any of these flights, just ask me!
"""
        else:
            return "I'll help you with that. What specific information are you looking for about the flights or email templates?"
    
    try:
        # Make the actual call to Bedrock Agent
        response = bedrock_agent_client.invoke_agent(
            agentId=AGENT_ID,
            agentAliasId=AGENT_ALIAS_ID,
            sessionId=session_id,
            inputText=prompt,
            enableTrace=True
        )
        
        # Process the response
        if 'completion' in response:
            event_stream = response['completion']
            full_response = ""
            
            # Extract content from event stream
            for event in event_stream:
                if 'chunk' in event and 'bytes' in event['chunk']:
                    try:
                        content_bytes = event['chunk']['bytes']
                        if isinstance(content_bytes, bytes):
                            decoded = content_bytes.decode('utf-8')
                            full_response += decoded
                    except Exception as e:
                        pass
            
            return full_response
        else:
            return "Sorry, I couldn't generate a response. Please try again."
    except Exception as e:
        return f"Error connecting to Bedrock Agent: {str(e)}"

def upload_template_to_s3(flight_id, email_subject, email_body):
    """Upload email template to S3"""
    try:
        # Format flight ID for filename
        short_id = flight_id[-5:] if flight_id else "default"
        
        # Format timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create filename
        filename = f"email_template_{short_id}_{timestamp}.txt"
        
        # Format email content
        email_content = f"Subject: {email_subject}\n\n{email_body}"
        
        # Save to S3
        s3_path = f"{EMAIL_TEMPLATES_PATH}{filename}"
        success = write_to_s3(BUCKET_NAME, s3_path, email_content)
        
        if success:
            return {
                "success": True,
                "filename": filename,
                "s3_path": s3_path,
                "url": f"s3://{BUCKET_NAME}/{s3_path}"
            }
        else:
            return {
                "success": False,
                "error": "Failed to write to S3"
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def get_segment_users(flight_id):
    """Get segment users for a flight"""
    try:
        segments = read_s3_json(BUCKET_NAME, SEGMENTS_OUTPUT_PATH)
        if not segments:
            return []
            
        for segment in segments:
            item_id = segment.get('input', {}).get('itemId')
            if item_id == flight_id:
                return segment.get('output', {}).get('usersList', [])
        
        return []
    except Exception as e:
        st.error(f"Error getting segment users: {str(e)}")
        return []

# Initialize AWS clients
s3_client, bedrock_agent_client = get_aws_clients()

# Sidebar
with st.sidebar:
    # App logo & title
    st.markdown('<div class="target-icon">🎯</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-header"><span class="app-name">1Shot</span></div>', unsafe_allow_html=True)
    st.markdown("---")
    
    # Navigation
    st.markdown("### Navigation")
    
    if st.button("📋 Select Flights", 
                key="nav_flights", 
                help="Browse and select flights for your campaign"):
        st.session_state.active_section = "flights"
        st.experimental_rerun()
    
    if st.button("✉️ Generate Emails", 
                key="nav_emails", 
                help="Generate personalized email content"):
        st.session_state.active_section = "emails"
        st.experimental_rerun()
    
    st.markdown("---")
    
    # Selection summary
    st.markdown("### Campaign Summary")
    
    if st.session_state.selected_flights:
        st.markdown(f"**Selected Flights:** {len(st.session_state.selected_flights)}")
        for i, flight in enumerate(st.session_state.selected_flights):
            st.markdown(f"- {flight['SRC_CITY']} to {flight['DST_CITY']}")
    else:
        st.markdown("No flights selected yet")
    
    if st.session_state.email_templates:
        st.markdown(f"**Email Templates:** {len(st.session_state.email_templates)}")
    else:
        st.markdown("No email templates generated yet")
    
    st.markdown("---")
    
    # Help section
    with st.expander("Help & Instructions"):
        st.markdown("""
        **How to use this app:**
        
        1. **Select Flights:** Choose promotional flights for your campaign
        2. **Generate Emails:** Create personalized email templates
        3. **Download User List:** Get the list of users to target
        4. **Upload to S3:** Save approved templates to S3
        
        Need further assistance? Contact support at support@1shot.com
        """)

# Main content area
st.markdown("# Email Marketing Campaign Generator")

# Display content based on active section
if st.session_state.active_section == "flights":
    st.markdown("## Select Promotional Flights")
    
    # Load flight data
    flight_df = read_s3_csv(BUCKET_NAME, ITEMS_CSV_PATH)
    
    if flight_df is not None:
        # Filter to show promotional flights
        promo_flights = flight_df[(flight_df['PROMOTION'] == 'Yes') & (flight_df['EXPIRED'] != 'Yes')]
        
        if promo_flights.empty:
            st.warning("No promotional flights found.")
        else:
            # Display info message
            st.markdown('<div class="info-box">Select flights to include in your marketing campaign</div>', unsafe_allow_html=True)
            
            # Add filters in two columns
            col1, col2 = st.columns(2)
            with col1:
                month_options = ["All"] + sorted(promo_flights['MONTH'].unique().tolist())
                selected_month = st.selectbox("Filter by Month", month_options)
                
            with col2:
                dest_options = ["All"] + sorted(promo_flights['DST_CITY'].unique().tolist())
                selected_dest = st.selectbox("Filter by Destination", dest_options)
            
            # Apply filters
            filtered_flights = promo_flights.copy()
            if selected_month != "All":
                filtered_flights = filtered_flights[filtered_flights['MONTH'] == selected_month]
            if selected_dest != "All":
                filtered_flights = filtered_flights[filtered_flights['DST_CITY'] == selected_dest]
            
            # Display flights in a table
            st.markdown("### Available Promotional Flights")
            st.dataframe(
                filtered_flights[['ITEM_ID', 'SRC_CITY', 'DST_CITY', 'AIRLINE', 'MONTH', 'DYNAMIC_PRICE', 'DURATION_DAYS']],
                column_config={
                    "ITEM_ID": "Flight ID",
                    "SRC_CITY": "From",
                    "DST_CITY": "To",
                    "AIRLINE": "Airline",
                    "MONTH": "Month",
                    "DYNAMIC_PRICE": st.column_config.NumberColumn("Price", format="$%d"),
                    "DURATION_DAYS": "Duration (days)"
                },
                use_container_width=True
            )
            
            # Selection form
            st.markdown("### Add Flight to Selection")
            flight_col1, flight_col2 = st.columns([3, 1])
            
            with flight_col1:
                new_flight_id = st.text_input(
                    "Enter Flight ID (copy from table above):",
                    help="Copy the Flight ID directly from the table above"
                )
            
            with flight_col2:
                if st.button("Add Flight", use_container_width=True):
                    if new_flight_id.strip() == "":
                        st.error("Please enter a Flight ID first")
                    else:
                        matching_flight = filtered_flights[filtered_flights['ITEM_ID'] == new_flight_id]
                        
                        if matching_flight.empty:
                            st.error(f"Flight ID {new_flight_id} not found in promotional flights")
                        else:
                            if new_flight_id not in [f['ITEM_ID'] for f in st.session_state.selected_flights]:
                                flight_data = matching_flight.iloc[0].to_dict()
                                st.session_state.selected_flights.append(flight_data)
                                st.success(f"Added flight from {flight_data['SRC_CITY']} to {flight_data['DST_CITY']}")
                                st.experimental_rerun()
                            else:
                                st.warning("This flight is already in your selection")
            
            # Display selected flights
            if st.session_state.selected_flights:
                st.markdown("### Selected Flights")
                
                for i, flight in enumerate(st.session_state.selected_flights):
                    col1, col2, col3 = st.columns([3, 1, 1])
                    with col1:
                        st.markdown(f"**{flight['SRC_CITY']} to {flight['DST_CITY']}** - {flight['AIRLINE']}, {flight['MONTH']}")
                    with col2:
                        st.markdown(f"${flight['DYNAMIC_PRICE']}")
                    with col3:
                        if st.button(f"Remove", key=f"remove_{i}"):
                            st.session_state.selected_flights.pop(i)
                            st.experimental_rerun()
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Clear All Selections", use_container_width=True):
                        st.session_state.selected_flights = []
                        st.experimental_rerun()
                
                with col2:
                    if st.button("Generate Email Templates", use_container_width=True):
                        st.session_state.active_section = "emails"
                        st.experimental_rerun()
                
                # Generate JSON button
                if st.button("Generate Segment Input JSON"):
                    flight_ids = [flight['ITEM_ID'] for flight in st.session_state.selected_flights]
                    json_content = create_segment_json(flight_ids)
                    
                    st.markdown("### Segment Input JSON")
                    st.markdown('<div class="success-box">Use this JSON file for batch segment job in Amazon Personalize</div>', unsafe_allow_html=True)
                    st.code(json_content, language="json")
                    
                    # Download button
                    st.download_button(
                        label="Download JSON File",
                        data=json_content,
                        file_name=f"batch_segment_input_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json"
                    )
    else:
        st.error("Could not load flight data.")

elif st.session_state.active_section == "emails":
    st.markdown("## Email Campaign Generator")
    
    if not st.session_state.selected_flights:
        st.warning("Please select flights first in the 'Select Flights' section")
        if st.button("Go Back to Flight Selection"):
            st.session_state.active_section = "flights"
            st.experimental_rerun()
    else:
        # Split the screen - left for chat, right for preview
        chat_col, preview_col = st.columns([3, 2])
        
        with chat_col:
            st.markdown("### Chat with 1Shot Assistant")
            
            # Check if segments exist
            segments_exist = False
            segments = read_s3_json(BUCKET_NAME, SEGMENTS_OUTPUT_PATH)
            if segments:
                flight_ids = [flight['ITEM_ID'] for flight in st.session_state.selected_flights]
                for segment in segments:
                    if segment.get('input', {}).get('itemId') in flight_ids:
                        segments_exist = True
                        break
            
            if not segments_exist:
                st.markdown('<div class="warning-box">No segment data is available yet. The assistant can still generate emails, but they won\'t be personalized based on segment analysis.</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="info-box">Segments are loaded. The assistant can generate personalized emails based on segment analysis.</div>', unsafe_allow_html=True)
            
            # Create scrollable chat container
            chat_container = st.container()
            
            with chat_container:
                st.markdown('<div class="chat-container" id="chat-container">', unsafe_allow_html=True)
                
                # Display chat history
                for message in st.session_state.chat_history:
                    if message["role"] == "user":
                        st.markdown(f'<div class="chat-message user"><div class="avatar">👤</div><div class="content">{message["content"]}</div></div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="chat-message assistant"><div class="avatar">🎯</div><div class="content">{message["content"]}</div></div>', unsafe_allow_html=True)
                
                st.markdown('</div>', unsafe_allow_html=True)
            
            # Get initial value from next_input if it exists
            initial_input = st.session_state.next_input
            # Clear next_input for next time
            st.session_state.next_input = ""
            
            # Input for new message
            user_input = st.text_input(
                "Your message:", 
                key="user_input", 
                value=initial_input,
                placeholder="Ask me to generate email templates..."
            )
            
            send_col, suggestion_col = st.columns([1, 3])
            
            with send_col:
                send_button = st.button("Send", use_container_width=True)
            
            with suggestion_col:
                # Quick suggestion buttons
                if st.button("Generate email for first flight", key="suggest1"):
                    if st.session_state.selected_flights:
                        flight = st.session_state.selected_flights[0]
                        st.session_state.next_input = f"Generate an email template for the {flight['SRC_CITY']} to {flight['DST_CITY']} flight"
                        st.experimental_rerun()
                
                if st.button("List user segments", key="suggest2"):
                    st.session_state.next_input = "List the available user segments for my selected flights"
                    st.experimental_rerun()
            
            if send_button and user_input:
                # Add user message to chat history
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                
                # Add context about selected flights to the prompt
                flight_context = "Selected flights:\n"
                for i, flight in enumerate(st.session_state.selected_flights):
                    flight_context += f"{i+1}. {flight['SRC_CITY']} to {flight['DST_CITY']} ({flight['AIRLINE']}, {flight['MONTH']}, ${flight['DYNAMIC_PRICE']})\n"
                
                # Construct the full prompt
                full_prompt = f"{flight_context}\n\nUser message: {user_input}"
                
                with st.spinner("Generating response..."):
                    # Get response from agent
                    assistant_response = invoke_agent(full_prompt)
                    
                    # Add assistant message to chat history
                    st.session_state.chat_history.append({"role": "assistant", "content": assistant_response})
                    
                    # Check if this looks like an email template
                    if "Subject:" in assistant_response or "subject:" in assistant_response.lower():
                        email_content = extract_email_content(assistant_response)
                        
                        # Store in session state for preview
                        if email_content["subject"] and email_content["body"]:
                            if len(st.session_state.selected_flights) > 0:
                                flight_id = st.session_state.selected_flights[0]["ITEM_ID"]
                                st.session_state.email_templates[flight_id] = email_content
                
                # Clear the input but don't directly modify session state
                st.experimental_rerun()
            
            # Clear chat button
            if st.button("Clear Chat"):
                st.session_state.chat_history = []
                st.experimental_rerun()
        
        with preview_col:
            st.markdown("### Email Preview")
            
            if not st.session_state.email_templates:
                st.info("No email templates generated yet. Chat with the assistant to create templates.")
            else:
                # If we have templates, let user select which one to preview
                if len(st.session_state.email_templates) > 1:
                    preview_options = []
                    for flight_id, _ in st.session_state.email_templates.items():
                        flight = next((f for f in st.session_state.selected_flights if f['ITEM_ID'] == flight_id), None)
                        if flight:
                            preview_options.append(f"{flight['SRC_CITY']} to {flight['DST_CITY']}")
                        else:
                            preview_options.append(f"Template {flight_id[-5:]}")
                    
                    selected_preview = st.selectbox("Select template to preview:", preview_options)
                    
                    # Find the flight_id for the selected preview
                    selected_index = preview_options.index(selected_preview)
                    selected_flight_id = list(st.session_state.email_templates.keys())[selected_index]
                else:
                    # Only one template
                    selected_flight_id = list(st.session_state.email_templates.keys())[0]
                
                # Display the selected template
                email_content = st.session_state.email_templates[selected_flight_id]
                
                st.markdown("<div class='email-preview'>", unsafe_allow_html=True)
                st.markdown(f"<h3>{email_content['subject']}</h3>", unsafe_allow_html=True)
                st.markdown("<hr>", unsafe_allow_html=True)
                
                # Format email body with line breaks
                formatted_body = email_content['body'].replace('\n', '<br>')
                st.markdown(f"{formatted_body}", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
                
                # Actions for the selected template
                st.markdown("### Template Actions")
                
                # Get segment users for this flight
                segment_users = get_segment_users(selected_flight_id)
                user_count = len(segment_users)
                
                # Display user segment information
                if user_count > 0:
                    st.markdown(f"**Users in segment:** {user_count}")
                    
                    # Show sample of user IDs
                    with st.expander("View sample users"):
                        sample_size = min(5, user_count)
                        st.code("\n".join(segment_users[:sample_size]) + ("\n..." if user_count > sample_size else ""))
                    
                    # Download user list button
                    user_list_csv = "USER_ID\n" + "\n".join(segment_users)
                    st.download_button(
                        label="Download User List (CSV)",
                        data=user_list_csv,
                        file_name=f"user_segment_{selected_flight_id[-5:]}.csv",
                        mime="text/csv"
                    )
                else:
                    st.warning("No user segment available for this flight.")
                
                # Template actions
                col1, col2 = st.columns(2)
                
                with col1:
                    # Download button for the email template
                    email_text = f"Subject: {email_content['subject']}\n\n{email_content['body']}"
                    st.download_button(
                        label="Download Template",
                        data=email_text,
                        file_name=f"email_template_{selected_flight_id[-5:]}.txt",
                        mime="text/plain"
                    )
                
                with col2:
                    # Button to upload template to S3
                    if st.button("Upload Template to S3", use_container_width=True):
                        with st.spinner("Uploading template to S3..."):
                            result = upload_template_to_s3(
                                selected_flight_id,
                                email_content['subject'],
                                email_content['body']
                            )
                            
                            if result['success']:
                                st.session_state.template_uploaded = True
                                st.session_state.template_upload_result = result
                                st.success(f"Template uploaded successfully: {result['url']}")
                            else:
                                st.error(f"Failed to upload template: {result.get('error', 'Unknown error')}")
                
                # If template was uploaded, show details
                if st.session_state.template_uploaded and hasattr(st.session_state, 'template_upload_result'):
                    result = st.session_state.template_upload_result
                    st.markdown('<div class="success-box">', unsafe_allow_html=True)
                    st.markdown(f"**Template uploaded to S3:**")
                    st.markdown(f"- **Path:** {result['s3_path']}")
                    st.markdown(f"- **URL:** {result['url']}")
                    st.markdown("</div>", unsafe_allow_html=True)
                
                # Button to enhance the template
                if st.button("Improve This Template"):
                    # Use next_input to store the suggestion instead of directly modifying user_input
                    st.session_state.next_input = "Please improve this email template. Make it more engaging and personal."
                    st.experimental_rerun()

# Add JavaScript to auto-scroll chat container to bottom
st.markdown("""
<script>
    // Function to scroll chat container to bottom
    function scrollToBottom() {
        const chatContainer = document.getElementById('chat-container');
        if (chatContainer) {
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
    }
    
    // Call function when page loads
    window.addEventListener('load', scrollToBottom);
    
    // Set up MutationObserver to detect changes in chat container
    const observer = new MutationObserver(scrollToBottom);
    
    // Start observing chat container for changes
    const chatContainer = document.getElementById('chat-container');
    if (chatContainer) {
        observer.observe(chatContainer, { childList: true, subtree: true });
    }
</script>
""", unsafe_allow_html=True)

# App footer
st.markdown("---")
st.markdown("### How to Use This Application")

with st.expander("App Instructions"):
    st.markdown("""
    1. **Select Flights**: Choose promotional flights to target in your campaign
    2. **Generate Emails**: Chat with the assistant to create personalized email templates
    3. **Download User List**: Get the list of users to target with your campaign
    4. **Upload to S3**: Save approved templates to S3 for use in your marketing system
    
    **Quick Tips:**
    - You can ask the assistant to generate templates for specific flights
    - Request enhancements to any template (e.g., "Make it more personalized")
    - Download both the email template and user list for your marketing platform
    """)

with st.expander("About 1Shot Email Marketing"):
    st.markdown("""
    This application showcases how to leverage user segmentation and generative AI to create highly targeted and personalized marketing campaigns:
    
    - **User Segmentation** identifies users with affinity for specific flights
    - **Email Content Generation** creates compelling marketing messages
    - **Interactive Refinement** allows for fine-tuning through natural language
    
    The tool helps marketing teams create personalized email campaigns targeting the right users with relevant content.
    """)