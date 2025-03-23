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

# Add your existing CSS styles here
st.markdown("""
<style>
    /* Your existing styles */
</style>
""", unsafe_allow_html=True)

# Initialize session state variables
if 'selected_flights' not in st.session_state:
    st.session_state.selected_flights = []

if 'email_templates' not in st.session_state:
    st.session_state.email_templates = {}

if 'active_section' not in st.session_state:
    st.session_state.active_section = "flights"

if 'segments_loaded' not in st.session_state:
    st.session_state.segments_loaded = False

# Configuration - modify these for your environment
BUCKET_NAME = os.environ.get(
    'S3_BUCKET_NAME', 'knowledgebase-bedrock-agent-ab3')
AGENT_ID = os.environ.get('AGENT_ID', '')
AGENT_ALIAS_ID = os.environ.get('AGENT_ALIAS_ID', 'TSTALIASID')
ITEMS_CSV_PATH = 'data/travel_items.csv'
USERS_CSV_PATH = 'data/travel_users.csv'
INTERACTIONS_CSV_PATH = 'data/travel_interactions.csv'
SEGMENTS_OUTPUT_PATH = 'segments/batch_segment_input_ab3.json.out'
EMAIL_TEMPLATES_PATH = 'email_templates/'

# Helper functions


@st.cache_resource
def get_aws_clients():
    try:
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
    subject_match = re.search(
        r'Subject:(.*?)(?:\n\n|\r\n\r\n)', response_text, re.IGNORECASE | re.DOTALL)
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
    if not email_content["subject"] and len(lines) > 0:
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

    # If agent client is not available or AGENT_ID is not set, use mock response with clear message
    if not bedrock_agent_client or not AGENT_ID:
        st.warning(
            "Agent ID not configured. Would connect to Bedrock Agent in production.")

        # Return a response that indicates this is a placeholder
        if "generate email" in prompt.lower() or "email template" in prompt.lower():
            return f"""
[This would invoke your Bedrock Agent in production]

Based on the prompt: "{prompt}"

Subject: Exclusive Flight Deal: Explore Hong Kong this October with PandaPaw Express

Dear Valued Traveler,

We're excited to offer you an exclusive opportunity to fly from Singapore to Hong Kong this October with PandaPaw Express!

✈️ FLIGHT DETAILS:
- Departure: Singapore
- Destination: Hong Kong
- Month: October 2023
- Airline: PandaPaw Express
- Duration: 10 days
- Special Price: $5,999 (Limited time offer!)

Hong Kong offers an incredible blend of urban excitement and natural beauty. During your stay, you can:
- Experience the breathtaking views from Victoria Peak
- Explore the vibrant Temple Street Night Market
- Enjoy authentic dim sum at Tim Ho Wan
- Visit the Big Buddha on Lantau Island
- Take a scenic ride on the Star Ferry

To take advantage of this exclusive offer, use promo code 2D066 when booking through our website at https://booking.pandapaw.example.com

Book now to secure your seat on this popular route!

Best regards,
The PandaPaw Express Team
"""
        else:
            return f"This would connect to your Bedrock Agent in production. Your prompt was: {prompt}"

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
                        st.error(f"Error processing agent response: {e}")

            return full_response
        else:
            return "Sorry, I couldn't generate a response. Please try again."
    except Exception as e:
        st.error(f"Error connecting to Bedrock Agent: {str(e)}")
        # Provide fallback response
        return f"""
[Fallback response due to agent connection error]

Subject: Special October Offer: Singapore to Hong Kong

Dear Valued Traveler,

We're pleased to offer you a special rate on our Singapore to Hong Kong flights this October with PandaPaw Express.

Take advantage of our limited-time promotion and book your trip today!

Best regards,
The PandaPaw Express Team
"""


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


def analyze_segment_patterns(flight_id):
    """Analyze segment patterns including rating trends"""
    segments = read_s3_json(BUCKET_NAME, SEGMENTS_OUTPUT_PATH)
    segment_users = []

    if segments:
        for segment in segments:
            if segment.get('input', {}).get('itemId') == flight_id:
                segment_users = segment.get('output', {}).get('usersList', [])
                break

    if not segment_users:
        return None

    # Load interactions data
    interactions_df = read_s3_csv(BUCKET_NAME, INTERACTIONS_CSV_PATH)
    if interactions_df is None:
        return None

    # Load users data for tier information
    users_df = read_s3_csv(BUCKET_NAME, USERS_CSV_PATH)

    # Filter for this flight and these users
    relevant_interactions = interactions_df[
        (interactions_df['ITEM_ID'] == flight_id) &
        (interactions_df['USER_ID'].isin(segment_users))
    ]

    if relevant_interactions.empty:
        return {
            "user_count": len(segment_users),
            "avg_rating": None,
            "cabin_ratings": {},
            "cabin_counts": {},
            "rating_distribution": {},
            "tier_distribution": {}
        }

    # Calculate average rating
    avg_rating = round(relevant_interactions['EVENT_VALUE'].mean(), 2)

    # Analyze by cabin type
    cabin_ratings = relevant_interactions.groupby(
        'CABIN_TYPE')['EVENT_VALUE'].mean().to_dict()
    cabin_counts = relevant_interactions.groupby('CABIN_TYPE').size().to_dict()

    # Get rating distribution
    rating_distribution = relevant_interactions['EVENT_VALUE'].value_counts(
    ).sort_index().to_dict()

    # Get tier distribution if users_df is available
    tier_distribution = {}
    if users_df is not None:
        tier_data = users_df[users_df['USER_ID'].isin(segment_users)]
        if not tier_data.empty:
            tier_distribution = tier_data['MEMBER_TIER'].value_counts(
            ).to_dict()

    return {
        "user_count": len(segment_users),
        "avg_rating": avg_rating,
        "cabin_ratings": cabin_ratings,
        "cabin_counts": cabin_counts,
        "rating_distribution": rating_distribution,
        "tier_distribution": tier_distribution
    }


# Initialize AWS clients
s3_client, bedrock_agent_client = get_aws_clients()

# Sidebar
with st.sidebar:
    st.markdown('<div class="target-icon">🎯</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-header"><span class="app-name">1Shot</span></div>',
                unsafe_allow_html=True)
    st.markdown("---")

    # Navigation
    st.markdown("### Navigation")

    # Simplified navigation
    tab = st.radio(
        "Select Section:",
        ["Flight Selection", "Segment Analysis", "Email Generator"]
    )

    # Set active section based on radio selection
    if tab == "Flight Selection":
        st.session_state.active_section = "flights"
    elif tab == "Segment Analysis":
        st.session_state.active_section = "segments"
    else:
        st.session_state.active_section = "emails"

    st.markdown("---")

    # Summary section
    st.markdown("### Campaign Summary")

    if st.session_state.selected_flights:
        st.markdown(
            f"**Selected Flights:** {len(st.session_state.selected_flights)}")
        for i, flight in enumerate(st.session_state.selected_flights):
            st.markdown(f"- {flight['SRC_CITY']} to {flight['DST_CITY']}")

            if st.button("❌", key=f"remove_{i}", help="Remove this flight"):
                st.session_state.selected_flights.pop(i)
                st.experimental_rerun()
    else:
        st.markdown("No flights selected yet")

    if st.button("Clear All Selections"):
        st.session_state.selected_flights = []
        st.experimental_rerun()

    st.markdown("---")

    # Help & Info
    with st.expander("About 1Shot Email Marketing"):
        st.markdown("""
       This application helps marketing teams create personalized email campaigns by:
       
       1. **Identifying Target Segments** - Find users with an affinity for specific flights
       2. **Analyzing Segment Patterns** - Understand user preferences and behavior
       3. **Generating Email Content** - Create compelling marketing messages tailored to each segment
       
       Select flights, analyze the user segments, and generate personalized email templates with just a few clicks.
       """)

# Main content area
st.markdown("# 1Shot Email Marketing Platform")

# Display content based on active section
if st.session_state.active_section == "flights":
    st.markdown("## Select Promotional Flights")

    # Load flight data
    flight_df = read_s3_csv(BUCKET_NAME, ITEMS_CSV_PATH)

    if flight_df is not None:
        # Filter to show promotional flights
        promo_flights = flight_df[(flight_df['PROMOTION'] == 'Yes') & (
            flight_df['EXPIRED'] != 'Yes')]

        if promo_flights.empty:
            st.warning("No promotional flights found.")
        else:
            # Display info message
            st.info("Select flights to include in your marketing campaign")

            # Add filters in two columns
            col1, col2 = st.columns(2)
            with col1:
                month_options = ["All"] + \
                    sorted(promo_flights['MONTH'].unique().tolist())
                selected_month = st.selectbox("Filter by Month", month_options)

            with col2:
                dest_options = ["All"] + \
                    sorted(promo_flights['DST_CITY'].unique().tolist())
                selected_dest = st.selectbox(
                    "Filter by Destination", dest_options)

            # Apply filters
            filtered_flights = promo_flights.copy()
            if selected_month != "All":
                filtered_flights = filtered_flights[filtered_flights['MONTH']
                                                    == selected_month]
            if selected_dest != "All":
                filtered_flights = filtered_flights[filtered_flights['DST_CITY']
                                                    == selected_dest]

            # Display flights as selectable cards
            st.markdown("### Available Flights")

            # Create a grid of cards
            cols = st.columns(3)
            for i, (_, flight) in enumerate(filtered_flights.iterrows()):
                col_idx = i % 3

                with cols[col_idx]:
                    with st.container():
                        st.markdown(f"""
                       <div style="padding: 15px; border-radius: 5px; margin-bottom: 15px; background-color: rgba(255, 255, 255, 0.05);">
                           <h4>{flight['SRC_CITY']} → {flight['DST_CITY']}</h4>
                           <p><b>Airline:</b> {flight['AIRLINE']}</p>
                           <p><b>Month:</b> {flight['MONTH']} | <b>Duration:</b> {flight['DURATION_DAYS']} days</p>
                           <p><b>Price:</b> ${flight['DYNAMIC_PRICE']}</p>
                       </div>
                       """, unsafe_allow_html=True)

                        if st.button("Select", key=f"select_{flight['ITEM_ID']}"):
                            # Check if already selected
                            if flight['ITEM_ID'] not in [f['ITEM_ID'] for f in st.session_state.selected_flights]:
                                flight_data = flight.to_dict()
                                st.session_state.selected_flights.append(
                                    flight_data)
                                st.success(f"Added flight to your selection")
                                st.experimental_rerun()
                            else:
                                st.warning(
                                    "This flight is already in your selection")

            # Button to generate segment input
            if st.session_state.selected_flights:
                st.markdown("### Generate Segment Input")

                if st.button("Generate JSON for Batch Segment Job"):
                    flight_ids = [flight['ITEM_ID']
                                  for flight in st.session_state.selected_flights]
                    json_content = create_segment_json(flight_ids)

                    st.code(json_content, language="json")

                    # Download button
                    st.download_button(
                        label="Download JSON File",
                        data=json_content,
                        file_name=f"batch_segment_input_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json"
                    )

                    st.success(
                        "Use this JSON file as input for your batch segment job in Amazon Personalize")
    else:
        st.error(
            "Could not load flight data. Please check your S3 bucket configuration.")

elif st.session_state.active_section == "segments":
    st.markdown("## Segment Analysis")

    if not st.session_state.selected_flights:
        st.warning(
            "No flights selected. Please select flights first in the Flight Selection section.")
    else:
        # Let user select a flight to analyze
        flight_options = [
            f"{flight['SRC_CITY']} to {flight['DST_CITY']} ({flight['AIRLINE']}, {flight['MONTH']})" for flight in st.session_state.selected_flights]
        flight_index = st.selectbox("Select a flight to analyze:", range(
            len(flight_options)), format_func=lambda i: flight_options[i])

        selected_flight = st.session_state.selected_flights[flight_index]
        flight_id = selected_flight['ITEM_ID']

        st.markdown(
            f"### Flight: {selected_flight['SRC_CITY']} to {selected_flight['DST_CITY']}")
        st.markdown(
            f"**Airline:** {selected_flight['AIRLINE']} | **Month:** {selected_flight['MONTH']} | **Price:** ${selected_flight['DYNAMIC_PRICE']}")

        # Get and display segment analysis
        with st.spinner("Analyzing segment data..."):
            analysis = analyze_segment_patterns(flight_id)

            if analysis:
                # User count and basic metrics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Users in Segment", analysis["user_count"])
                with col2:
                    st.metric(
                        "Average Rating", analysis["avg_rating"] if analysis["avg_rating"] else "N/A")
                with col3:
                    # Most common tier
                    if analysis["tier_distribution"]:
                        top_tier = max(
                            analysis["tier_distribution"].items(), key=lambda x: x[1])
                        st.metric("Top Member Tier",
                                  f"{top_tier[0]} ({top_tier[1]} users)")
                    else:
                        st.metric("Top Member Tier", "N/A")

                # Rating distribution
                if analysis["rating_distribution"]:
                    st.markdown("### Rating Distribution")

                    # Convert to DataFrame for charting
                    rating_data = pd.DataFrame({
                        "Rating": list(analysis["rating_distribution"].keys()),
                        "Count": list(analysis["rating_distribution"].values())
                    })

                    # Sort by rating
                    rating_data = rating_data.sort_values(by="Rating")

                    # Display bar chart
                    st.bar_chart(rating_data.set_index("Rating"))

                # Cabin type analysis
                if analysis["cabin_ratings"]:
                    st.markdown("### Cabin Type Analysis")

                    # Create a DataFrame for the cabin data
                    cabin_data = []
                    for cabin, rating in analysis["cabin_ratings"].items():
                        cabin_data.append({
                            "Cabin Type": cabin,
                            "Average Rating": round(rating, 2),
                            "User Count": analysis["cabin_counts"].get(cabin, 0)
                        })

                    cabin_df = pd.DataFrame(cabin_data)

                    # Display as table
                    st.dataframe(cabin_df)

                    # Also show as chart
                    st.bar_chart(cabin_df.set_index(
                        "Cabin Type")[["Average Rating"]])

                # Member tier distribution
                if analysis["tier_distribution"]:
                    st.markdown("### Member Tier Distribution")

                    # Create DataFrame for tier distribution
                    tier_data = pd.DataFrame({
                        "Tier": list(analysis["tier_distribution"].keys()),
                        "Count": list(analysis["tier_distribution"].values())
                    })

                    # Display as chart
                    st.bar_chart(tier_data.set_index("Tier"))

                # Sample users section (truncated for privacy)
                with st.expander("View Sample Users"):
                    segment_users = get_segment_users(flight_id)
                    if segment_users:
                        # Just show 5 for demo
                        sample_users = segment_users[:5]
                        st.code("\n".join(sample_users))
                        st.caption(f"Showing 5 of {len(segment_users)} users")
                    else:
                        st.info("No user data available")
            else:
                st.warning(
                    "No segment data available for this flight. Please ensure you've run a batch segment job in Amazon Personalize.")

                # Generate sample data button for demo purposes
                if st.button("Generate Sample Analysis Data (Demo)"):
                    st.info(
                        "This would show actual segment analysis in production. Below is sample data for demonstration.")

                    # Mock chart data
                    rating_data = pd.DataFrame({
                        "Rating": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                        "Count": [3, 5, 8, 12, 18, 25, 35, 28, 20, 15]
                    })

                    st.markdown("### Rating Distribution (Sample)")
                    st.bar_chart(rating_data.set_index("Rating"))

                    cabin_data = pd.DataFrame({
                        "Cabin Type": ["Economy", "Business", "First Class"],
                        "Average Rating": [7.2, 8.5, 9.1],
                        "User Count": [120, 45, 15]
                    })

                    st.markdown("### Cabin Type Analysis (Sample)")
                    st.dataframe(cabin_data)
                    st.bar_chart(cabin_data.set_index(
                        "Cabin Type")[["Average Rating"]])

elif st.session_state.active_section == "emails":
    st.markdown("## Email Template Generator")

    if not st.session_state.selected_flights:
        st.warning(
            "No flights selected. Please select flights first in the Flight Selection section.")
    else:
        # Let user select which flight to generate email for
        flight_options = [
            f"{flight['SRC_CITY']} to {flight['DST_CITY']} ({flight['AIRLINE']}, {flight['MONTH']})" for flight in st.session_state.selected_flights]
        flight_index = st.selectbox("Select a flight:", range(
            len(flight_options)), format_func=lambda i: flight_options[i])

        selected_flight = st.session_state.selected_flights[flight_index]
        flight_id = selected_flight['ITEM_ID']

        # Email generation options
        st.markdown("### Generation Options")

        col1, col2 = st.columns(2)
        with col1:
            template_style = st.selectbox(
                "Email Style:",
                ["Promotional", "Informational",
                    "Exclusive Offer", "Last Minute Deal"]
            )

            include_activities = st.checkbox(
                "Include destination activities", value=True)
            include_testimonials = st.checkbox(
                "Include customer testimonials", value=False)

        with col2:
            tone = st.selectbox(
                "Tone:",
                ["Professional", "Friendly", "Luxury", "Casual"]
            )

            include_images = st.checkbox("Mention banner images", value=True)
            highlight_discount = st.checkbox("Highlight discount", value=True)

        # Generate button
        if st.button("Generate Email Template", use_container_width=True):
            with st.spinner("Generating template..."):
                # Build a detailed prompt
                prompt = f"""Generate a {template_style} email template with a {tone} tone for a flight from {selected_flight['SRC_CITY']} to {selected_flight['DST_CITY']} in {selected_flight['MONTH']}, operated by {selected_flight['AIRLINE']}.

Flight details:
- Price: ${selected_flight['DYNAMIC_PRICE']}
- Duration: {selected_flight['DURATION_DAYS']} days
- Promotion code: {selected_flight['ITEM_ID'][-5:]}

Include:"""

                if include_activities:
                    prompt += "\n- Popular activities and attractions in the destination"
                if include_testimonials:
                    prompt += "\n- A customer testimonial or two"
                if include_images:
                    prompt += "\n- References to banner images showing the destination"
                if highlight_discount:
                    prompt += "\n- Emphasis on special pricing and limited-time offer"

                prompt += "\n\nFormat the response with a clear subject line that starts with 'Subject:' followed by two line breaks and then the email body."

                # Invoke agent or process locally
                response = invoke_agent(prompt)

                # Process the response
                email_content = extract_email_content(response)

                # Store in session state
                st.session_state.email_templates[flight_id] = email_content

        # Display the generated template
        if flight_id in st.session_state.email_templates:
            email_content = st.session_state.email_templates[flight_id]

            st.markdown("### Generated Email Template")

            # Email preview box
            st.markdown(
                "<div style='padding: 20px; border-radius: 5px; background-color: rgba(255, 255, 255, 0.05); margin-bottom: 20px;'>", unsafe_allow_html=True)
            st.markdown(
                f"<h3>{email_content['subject']}</h3>", unsafe_allow_html=True)
            st.markdown("<hr>", unsafe_allow_html=True)

            # Format the email body with proper line breaks
            formatted_body = email_content['body'].replace('\n', '<br>')
            st.markdown(f"{formatted_body}", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

            # Actions for the email
            col1, col2 = st.columns(2)

            with col1:
                # Download button
                email_text = f"Subject: {email_content['subject']}\n\n{email_content['body']}"
                st.download_button(
                    label="Download Email Template",
                    data=email_text,
                    file_name=f"email_{selected_flight['SRC_CITY']}_{selected_flight['DST_CITY']}_{datetime.now().strftime('%Y%m%d')}.txt",
                    mime="text/plain",
                    use_container_width=True
                )

            with col2:
                # Regenerate button
                if st.button("Regenerate Template", use_container_width=True):
                    # Remove from session state to trigger regeneration
                    if flight_id in st.session_state.email_templates:
                        del st.session_state.email_templates[flight_id]
                    st.experimental_rerun()

            # Get segment info
            segment_users = get_segment_users(flight_id)
            user_count = len(segment_users)

            if user_count > 0:
                st.success(
                    f"This email can be sent to {user_count} users in the segment.")

                # User list download
                st.download_button(
                    label=f"Download User List ({user_count} users)",
                    data="\n".join(segment_users),
                    file_name=f"users_{selected_flight['SRC_CITY']}_{selected_flight['DST_CITY']}.txt",
                    mime="text/plain"
                )
            else:
                st.info(
                    "No user segment available for this flight. Run a batch segment job in Amazon Personalize first.")
        else:
            st.info(
                "Click 'Generate Email Template' to create a personalized marketing email.")
