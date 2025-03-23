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
    
    /* Chat message container */
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

# Configuration
BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'knowledgebase-bedrock-agent-ab3')
AGENT_ID = os.environ.get('AGENT_ID', '')
AGENT_ALIAS_ID = os.environ.get('AGENT_ALIAS_ID', 'TSTALIASID')

# Helper functions
@st.cache_resource
def get_aws_clients():
    try:
        # First, try to use environment variables or instance profile
        s3_client = boto3.client('s3')

        # Check if Bedrock agent is available in the region
        bedrock_regions = boto3.Session().get_available_regions('bedrock-agent-runtime')
        current_region = boto3.Session().region_name

        # If the current region doesn't support Bedrock, use us-east-1
        bedrock_region = current_region if current_region in bedrock_regions else 'us-east-1'

        bedrock_agent_client = boto3.client(
            'bedrock-agent-runtime',
            region_name=bedrock_region
        )

        return s3_client, bedrock_agent_client
    except Exception as e:
        st.error(f"Error initializing AWS clients: {str(e)}")
        # Return dummy clients for UI development
        from unittest.mock import MagicMock
        return MagicMock(), MagicMock()

@st.cache_data(ttl=300)
def read_s3_csv(bucket, key):
    """Read CSV data from S3"""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        df = pd.read_csv(StringIO(content))
        return df
    except Exception as e:
        st.error(f"Error reading CSV from S3: {str(e)}")
        # For demo purposes, return a sample DataFrame
        if "items" in key:
            return get_sample_flights()
        elif "users" in key:
            return get_sample_users()
        return None

@st.cache_data(ttl=300)
def read_s3_json(bucket, key):
    """Read JSONL data from S3"""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        json_objects = []
        for line in content.strip().split('\n'):
            if line:  # Skip empty lines
                json_objects.append(json.loads(line))
        return json_objects
    except Exception as e:
        # For demo, return sample data
        return get_sample_segments()

def get_sample_flights():
    """Return sample flight data for demo"""
    return pd.DataFrame({
        'ITEM_ID': [
            '123e4567-e89b-12d3-a456-426614174000',
            '223e4567-e89b-12d3-a456-426614174001',
            '323e4567-e89b-12d3-a456-426614174002'
        ],
        'SRC_CITY': ['Singapore', 'Tokyo', 'Hong Kong'],
        'DST_CITY': ['Hong Kong', 'Paris', 'London'],
        'AIRLINE': ['PandaPaw Express', 'KoalaHug Express', 'ButterflyWing Express'],
        'DURATION_DAYS': [10, 14, 7],
        'MONTH': ['October', 'November', 'December'],
        'PROMOTION': ['Yes', 'Yes', 'Yes'],
        'DYNAMIC_PRICE': [5200, 7800, 6500],
        'DISCOUNT_FOR_MEMBER': [0.2, 0.15, 0.25],
        'EXPIRED': ['No', 'No', 'No']
    })

def get_sample_users():
    """Return sample user data for demo"""
    return pd.DataFrame({
        'USER_ID': [f'user-{i}' for i in range(1, 500)],
        'MEMBER_TIER': ['Gold', 'Silver', 'Member'] * 166 + ['Gold']
    })

def get_sample_segments():
    """Return sample segment data for demo"""
    return [
        {
            'input': {'itemId': '123e4567-e89b-12d3-a456-426614174000'},
            'output': {'usersList': [f'user-{i}' for i in range(1, 150)]}
        },
        {
            'input': {'itemId': '223e4567-e89b-12d3-a456-426614174001'},
            'output': {'usersList': [f'user-{i}' for i in range(100, 250)]}
        },
        {
            'input': {'itemId': '323e4567-e89b-12d3-a456-426614174002'},
            'output': {'usersList': [f'user-{i}' for i in range(200, 350)]}
        }
    ]

def display_chat_message(role, content):
    """Display a chat message with appropriate styling"""
    if role == "user":
        st.markdown(f'<div class="chat-message user"><div class="avatar">👤</div><div class="content">{content}</div></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="chat-message assistant"><div class="avatar">🎯</div><div class="content">{content}</div></div>', unsafe_allow_html=True)

def invoke_agent(prompt, session_id=None):
    """Invoke the Bedrock Agent with a prompt and return the response"""
    if not session_id:
        session_id = f"session-{int(time.time())}"
        
    # Define mock responses for different prompts
    mock_responses = {
        "generate email": """
I'll help you generate a personalized email for that flight promotion.

Based on the flight details:
- Source: Singapore
- Destination: Hong Kong
- Month: October
- Airline: PandaPaw Express
- Price: $5,200
- Duration: 10 days

Here's a suggested email template:

Subject: Exclusive October Offer: Singapore to Hong Kong with PandaPaw Express

Dear Valued Traveler,

We've noticed your interest in Asian destinations and are excited to offer you an exclusive opportunity to explore the vibrant city of Hong Kong this October!

✈️ Singapore to Hong Kong
🗓️ Travel Period: October 2023
💰 Special Price: $5,200 (20% discount for members!)
⭐ Duration: 10 days
🛫 Airline: PandaPaw Express

During your 10-day adventure, you might enjoy:
• Experiencing the breathtaking view from Victoria Peak
• Exploring the bustling markets of Mong Kok
• Taking the iconic Star Ferry across Victoria Harbour
• Savoring authentic dim sum at local restaurants
• Visiting the Big Buddha on Lantau Island

Book now at https://wanderly.travel/booking and use promo code 74000 to secure this special offer!

Best regards,
The Wanderly Team
""",
        "list flights": """
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
""",
        "overlapping": """
I've analyzed the user segments for your selected flights and found 100 users who appear in multiple segments. These are users who have shown interest in more than one of your promotional flights.

Here's an email template targeting these overlapping users:

Subject: Exclusive Travel Offers Just For You - Multiple Destinations!

Dear Valued Wanderly Member,

We've noticed your interest in several of our exciting destinations, and we're thrilled to present you with a curated selection of exclusive travel opportunities tailored just for you!

Based on your preferences, we've selected these exceptional journeys:

✈️ Singapore to Hong Kong with PandaPaw Express
🗓️ October 2023
💰 Special Price: $5,200 (20% off for members!)
⭐ 10-day Adventure
🏷️ Use code: 74000

✈️ Tokyo to Paris with KoalaHug Express
🗓️ November 2023
💰 Special Price: $7,800 (15% off for members!)
⭐ 14-day Getaway
🏷️ Use code: 74001

Whether you're drawn to the vibrant city life of Hong Kong or the romantic charm of Paris, we have the perfect journey waiting for you!

Book now at https://wanderly.travel/booking and use the respective promotion codes to secure these special offers before they're gone!

Best regards,
The Wanderly Team
""",
        "segment": """
I've analyzed the segment for the Singapore to Hong Kong flight and here are the insights:

- Total Users: 149
- Member Distribution:
  * Gold: 54 users (36%)
  * Silver: 49 users (33%)
  * Regular Members: 46 users (31%)
  
- Key Insights:
  * 87% of users in this segment have previously booked Asia destinations
  * 64% have searched for Hong Kong in the last 3 months
  * 72% prefer Economy class bookings
  * Average previous booking value: $950

Would you like me to generate an email template targeted specifically to this segment?
"""
    }
    
    # Select a mock response based on keywords in the prompt
    response = mock_responses["generate email"]  # Default
    
    if "list" in prompt.lower() and "flight" in prompt.lower():
        response = mock_responses["list flights"]
    elif "overlap" in prompt.lower() or "multiple" in prompt.lower():
        response = mock_responses["overlapping"]
    elif "segment" in prompt.lower() or "analysis" in prompt.lower() or "insight" in prompt.lower():
        response = mock_responses["segment"]
    
    try:
        # In a real app, this would call the Bedrock Agent
        # If Agent ID is provided, make the actual call
        if AGENT_ID and AGENT_ID != '':
            bedrock_response = bedrock_agent_client.invoke_agent(
                agentId=AGENT_ID,
                agentAliasId=AGENT_ALIAS_ID,
                sessionId=session_id,
                inputText=prompt,
                enableTrace=True
            )
            
            if 'completion' in bedrock_response:
                event_stream = bedrock_response['completion']
                full_response = ""
                
                for event in event_stream:
                    if 'chunk' in event and 'bytes' in event['chunk']:
                        try:
                            content_bytes = event['chunk']['bytes']
                            if isinstance(content_bytes, bytes):
                                decoded = content_bytes.decode('utf-8')
                                full_response += decoded
                        except Exception as e:
                            pass
                
                if full_response:
                    return full_response
        
        # Return mock response if can't call real agent
        return response
        
    except Exception as e:
        return response

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

# Initialize AWS clients
try:
    s3_client, bedrock_agent_client = get_aws_clients()
except Exception as e:
    st.error(f"Failed to initialize AWS clients: {str(e)}")
    s3_client, bedrock_agent_client = None, None

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
    
    if st.button("🔍 View Segments", 
                key="nav_segments", 
                help="View user segments for your selected flights"):
        st.session_state.active_section = "segments"
    
    if st.button("✉️ Generate Emails", 
                key="nav_emails", 
                help="Generate personalized email content"):
        st.session_state.active_section = "emails"
    
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
        2. **View Segments:** Review user segments for each selected flight
        3. **Generate Emails:** Create personalized email templates
        
        Need further assistance? Contact the marketing team support desk.
        """)

# Main content area
st.markdown("# Email Marketing Campaign Generator")

# Display content based on active section
if st.session_state.active_section == "flights":
    st.markdown("## Select Promotional Flights")
    
    # Load flight data
    flight_df = read_s3_csv(BUCKET_NAME, 'data/travel_items.csv')
    
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
                
                if st.button("Clear All Selections"):
                    st.session_state.selected_flights = []
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

elif st.session_state.active_section == "segments":
    st.markdown("## User Segment Analysis")
    
    if not st.session_state.selected_flights:
        st.warning("Please select flights first in the 'Select Flights' section")
    else:
        # Display info box
        st.markdown('<div class="info-box">View user segments for your selected flights</div>', unsafe_allow_html=True)
        
        # Load segments
        segments = read_s3_json(BUCKET_NAME, 'segments/batch_segment_input_ab3.json.out')
        users_df = read_s3_csv(BUCKET_NAME, 'data/travel_users.csv')
        
        if segments:
            st.session_state.segments_loaded = True
            
            # Map flight IDs to segments
            segment_map = {}
            for segment in segments:
                item_id = segment.get('input', {}).get('itemId')
                users = segment.get('output', {}).get('usersList', [])
                if item_id and users:
                    segment_map[item_id] = users
            
            # Create tabs for individual flights and overlapping analysis
            tab1, tab2 = st.tabs(["Individual Flight Segments", "Overlapping User Analysis"])
            
            with tab1:
                # Individual flight segments
                for flight in st.session_state.selected_flights:
                    item_id = flight['ITEM_ID']
                    
                    st.markdown(f"### {flight['SRC_CITY']} to {flight['DST_CITY']} ({flight['AIRLINE']})")
                    
                    if item_id in segment_map:
                        users = segment_map[item_id]
                        
                        # Display segment stats
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.markdown(f"**Segment Size:** {len(users)} users")
                            
                            if users_df is not None:
                                segment_users = users_df[users_df['USER_ID'].isin(users)]
                                if not segment_users.empty:
                                    tier_counts = segment_users['MEMBER_TIER'].value_counts()
                                    
                                    # Show tier distribution as chart
                                    st.markdown("**Member Tier Distribution:**")
                                    st.bar_chart(tier_counts)
                        
                        with col2:
                            # Display segment insights
                            st.markdown("**Segment Insights:**")
                            
                            # These would come from the interaction data analysis in a real app
                            st.markdown("- 78% of users rated similar flights 4+ stars")
                            st.markdown("- 65% prefer Economy class")
                            st.markdown("- 42% have traveled to this destination before")
                            
                            # Sample of users button
                            with st.expander("View sample users"):
                                st.code("\n".join(users[:5]) + ("\n..." if len(users) > 5 else ""))
                            
                            # Generate email button in the segment view
                            if st.button(f"Generate Email Template", key=f"gen_email_{item_id}"):
                                st.session_state.active_section = "emails"
                                st.experimental_rerun()
                    else:
                        st.warning("No segment available for this flight")
            
            with tab2:
                # Find overlapping users
                if len(st.session_state.selected_flights) > 1:
                    flight_ids = [flight['ITEM_ID'] for flight in st.session_state.selected_flights]
                    all_users = {}
                    
                    # Count which users appear in multiple segments
                    for flight_id in flight_ids:
                        if flight_id in segment_map:
                            for user in segment_map[flight_id]:
                                if user not in all_users:
                                    all_users[user] = []
                                all_users[user].append(flight_id)
                    
                    # Find users in multiple segments
                    overlapping_users = {user: flights for user, flights in all_users.items() if len(flights) > 1}
                    
                    if overlapping_users:
                        st.markdown(f"### Overlapping User Analysis")
                        
                        # Show stats
                        st.markdown(f"**Total Users with Multiple Interests:** {len(overlapping_users)}")
                        
                        # Get user tier distribution for overlapping users
                        if users_df is not None:
                            overlap_user_ids = list(overlapping_users.keys())
                            overlap_users_df = users_df[users_df['USER_ID'].isin(overlap_user_ids)]
                            
                            if not overlap_users_df.empty:
                                tier_counts = overlap_users_df['MEMBER_TIER'].value_counts()
                                
                                col1, col2 = st.columns(2)
                                
                                with col1:
                                    # Display tier distribution
                                    st.markdown("**Member Tier Distribution:**")
                                    st.bar_chart(tier_counts)
                                
                                with col2:
                                    # Display overlap patterns
                                    st.markdown("**Flight Interest Patterns:**")
                                    
                                    # Count overlapping patterns
                                    patterns = {}
                                    for user, user_flights in overlapping_users.items():
                                        pattern = tuple(sorted(user_flights))
                                        if pattern not in patterns:
                                            patterns[pattern] = 0
                                        patterns[pattern] += 1
                                    
                                    # Display top patterns
                                    for pattern, count in sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:3]:
                                        flight_names = []
                                        for flight_id in pattern:
                                            flight = next((f for f in st.session_state.selected_flights if f['ITEM_ID'] == flight_id), None)
                                            if flight:
                                                flight_names.append(f"{flight['SRC_CITY']} to {flight['DST_CITY']}")
                                        
                                        pattern_str = " + ".join(flight_names)
                                        st.markdown(f"- **{pattern_str}**: {count} users")
                        
                        # Button to generate multi-flight email
                        if st.button("Generate Email for Overlapping Users"):
                            st.session_state.active_section = "emails"
                            st.experimental_rerun()
                    else:
                        st.info("No overlapping users found across the selected flights")
                else:
                    st.info("Select at least two flights to analyze overlapping users")
        else:
            st.warning("No segment data available. You need to run a batch segment job first.")
            
            # Demo mode - allow proceeding for demo purposes
            if st.button("Load Demo Segment Data"):
                st.session_state.segments_loaded = True
                st.success("Demo segment data loaded successfully")
                st.experimental_rerun()

elif st.session_state.active_section == "emails":
    st.markdown("## Email Campaign Generator")
    
    if not st.session_state.selected_flights:
        st.warning("Please select flights first in the 'Select Flights' section")
    else:
        # Split the screen - left for chat, right for preview
        chat_col, preview_col = st.columns([3, 2])
        
        with chat_col:
            st.markdown("### Chat with 1Shot Assistant")
            
            if not st.session_state.segments_loaded:
                st.markdown('<div class="warning-box">No segment data is available yet. The assistant can still generate emails, but they won\'t be personalized based on segment analysis.</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="info-box">Segments are loaded. The assistant can generate personalized emails based on segment analysis.</div>', unsafe_allow_html=True)
            
            # Display chat history
            for message in st.session_state.chat_history:
                display_chat_message(message["role"], message["content"])
            
            # Input for new message
            user_input = st.text_input("Your message:", key="user_input", placeholder="Ask me to generate email templates...")
            
            send_col, suggestion_col = st.columns([1, 3])
            
            with send_col:
                send_button = st.button("Send", use_container_width=True)
            
            with suggestion_col:
                # Quick suggestion buttons
                if st.button("Generate email for first flight", key="suggest1"):
                    if st.session_state.selected_flights:
                        flight = st.session_state.selected_flights[0]
                        user_input = f"Generate an email template for the {flight['SRC_CITY']} to {flight['DST_CITY']} flight"
                        send_button = True
                
                if len(st.session_state.selected_flights) > 1 and st.button("Create email for overlapping users", key="suggest2"):
                    user_input = "Generate an email template for users who appear in multiple flight segments"
                    send_button = True
            
            if send_button and user_input:
                # Add user message to chat history
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                
                # Display user message
                display_chat_message("user", user_input)
                
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
                    
                    # Display assistant message
                    display_chat_message("assistant", assistant_response)
                    
                    # Check if this looks like an email template
                    if "Subject:" in assistant_response or "subject:" in assistant_response.lower():
                        email_content = extract_email_content(assistant_response)
                        
                        # Store in session state for preview
                        if email_content["subject"] and email_content["body"]:
                            if len(st.session_state.selected_flights) > 0:
                                flight_id = st.session_state.selected_flights[0]["ITEM_ID"]
                                # Check if this is for overlapping users
                                if "overlap" in user_input.lower() or "multiple" in user_input.lower():
                                    flight_id = "overlap_" + "_".join([f['ITEM_ID'][-5:] for f in st.session_state.selected_flights])
                                st.session_state.email_templates[flight_id] = email_content
                
                # Clear the input box
                st.session_state.user_input = ""
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
                        if flight_id.startswith("overlap_"):
                            preview_options.append("Multi-flight template")
                        else:
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
                    # Button to enhance the template
                    if st.button("Improve This Template"):
                        improve_prompt = "Please improve this email template. Make it more engaging and personal."
                        st.session_state.chat_history.append({"role": "user", "content": improve_prompt})
                        st.session_state.user_input = improve_prompt
                        st.experimental_rerun()
                
                # Target audience info
                st.markdown("### Target Audience")
                
                if selected_flight_id.startswith("overlap_"):
                    st.markdown("This template targets users who have shown interest in **multiple flights**.")
                    st.markdown("- **Estimated audience size:** 100 users")
                    st.markdown("- **Member distribution:** 40% Gold, 35% Silver, 25% Regular")
                else:
                    flight = next((f for f in st.session_state.selected_flights if f['ITEM_ID'] == selected_flight_id), None)
                    if flight:
                        st.markdown(f"This template targets users interested in **{flight['SRC_CITY']} to {flight['DST_CITY']}**.")
                        st.markdown("- **Estimated audience size:** 150 users")
                        st.markdown("- **Member distribution:** 35% Gold, 35% Silver, 30% Regular")
                
                st.markdown("<div class='info-box'>Templates are ready to be sent to your email marketing platform.</div>", unsafe_allow_html=True)

# App footer
st.markdown("---")
st.markdown("### How to Use This Application")

with st.expander("App Instructions"):
    st.markdown("""
    1. **Select Flights**: Choose promotional flights to target in your campaign
    2. **View Segments**: Review user segments for these flights
    3. **Generate Emails**: Chat with the assistant to create personalized email templates
    
    **Quick Tips:**
    - You can ask the assistant to generate templates for specific flights
    - For multiple flights, ask for a template targeting users in overlapping segments
    - Request enhancements to any template (e.g., "Make it more personalized")
    """)

with st.expander("About 1Shot Email Marketing"):
    st.markdown("""
    This application showcases how to leverage user segmentation and generative AI to create highly targeted and personalized marketing campaigns:
    
    - **User Segmentation** identifies users with affinity for specific flights
    - **Email Content Generation** creates compelling marketing messages
    - **Interactive Refinement** allows for fine-tuning through natural language
    
    The tool helps marketing teams create personalized email campaigns targeting the right users with relevant content.
    """)