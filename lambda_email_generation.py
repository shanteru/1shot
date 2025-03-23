import json
import boto3
import pandas as pd
from io import StringIO
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    # ============= CONFIGURATION CONSTANTS =============
    # S3 bucket configuration
    BUCKET_NAME = 'knowledgebase-bedrock-agent-ab3'
    
    # Data file paths
    ITEMS_CSV_PATH = 'data/travel_items.csv'
    USERS_CSV_PATH = 'data/travel_users.csv'
    INTERACTIONS_CSV_PATH = 'data/travel_interactions.csv'
    
    # Segment file paths
    SEGMENT_OUTPUT_PATH = 'segments/batch_segment_input_ab3.json.out'
    
    # Email template storage
    EMAIL_TEMPLATE_PATH = 'email_templates/'
    # ============= END CONFIGURATION =============
    
    logger.info(f"Event received: {json.dumps(event)}")

    # Initialize S3 client
    s3_client = boto3.client('s3')
    
    def get_named_parameter(event, name, default=None):
        """Safely get a named parameter from the event"""
        try:
            return next((item['value'] for item in event.get('parameters', [])
                        if item['name'] == name), default)
        except (KeyError, StopIteration):
            logger.warning(f"Parameter {name} not found in event")
            return default

    def read_s3_json(bucket, key):
        """Read JSONL data from S3"""
        try:
            logger.info(f"Reading JSON from s3://{bucket}/{key}")
            response = s3_client.get_object(Bucket=bucket, Key=key)
            content = response['Body'].read().decode('utf-8')
            # Split content by lines and parse each line as separate JSON
            json_objects = []
            for line in content.strip().split('\n'):
                if line:  # Skip empty lines
                    json_objects.append(json.loads(line))
            logger.info(f"Successfully read {len(json_objects)} JSON objects")
            return json_objects
        except Exception as e:
            logger.error(f"Error reading JSON from S3: {str(e)}")
            return None

    def read_s3_csv(bucket, key):
        """Read CSV data from S3"""
        try:
            logger.info(f"Reading CSV from s3://{bucket}/{key}")
            response = s3_client.get_object(Bucket=bucket, Key=key)
            content = response['Body'].read().decode('utf-8')
            df = pd.read_csv(StringIO(content))
            logger.info(f"Successfully read CSV with {len(df)} rows")
            return df
        except Exception as e:
            logger.error(f"Error reading CSV from S3: {str(e)}")
            return None
    
    def write_to_s3(bucket, key, content):
        """Write content to S3"""
        try:
            logger.info(f"Writing to s3://{bucket}/{key}")
            s3_client.put_object(
                Bucket=bucket,
                Key=key,
                Body=content
            )
            return True
        except Exception as e:
            logger.error(f"Error writing to S3: {str(e)}")
            return False
    
    def get_segment_output(bucket):
        """Get segment output files from S3"""
        try:
            return read_s3_json(bucket, SEGMENT_OUTPUT_PATH)
        except Exception as e:
            logger.error(f"Error getting segment output: {str(e)}")
            return None
    
    def get_flight_details(item_id):
        """Get flight details from items data"""
        items_df = read_s3_csv(BUCKET_NAME, ITEMS_CSV_PATH)
        if items_df is None:
            logger.error("Failed to read items CSV")
            return None

        flight = items_df[items_df['ITEM_ID'] == item_id]
        if flight.empty:
            logger.warning(f"No flight found with ITEM_ID: {item_id}")
            return None

        return flight.iloc[0].to_dict()
    
    def list_available_segments(event):
        """List all available segments from the batch output file"""
        segments = get_segment_output(BUCKET_NAME)
        
        if not segments:
            return {
                "status": "warning",
                "message": "No segment data available"
            }
        
        segment_info = []
        for segment in segments:
            item_id = segment.get('input', {}).get('itemId')
            users = segment.get('output', {}).get('usersList', [])
            
            flight_details = get_flight_details(item_id)
            if flight_details:
                segment_info.append({
                    "flightId": item_id,
                    "source": flight_details.get('SRC_CITY'),
                    "destination": flight_details.get('DST_CITY'),
                    "airline": flight_details.get('AIRLINE'),
                    "month": flight_details.get('MONTH'),
                    "userCount": len(users)
                })
        
        return {
            "status": "success",
            "segments": segment_info,
            "totalSegments": len(segment_info)
        }
    
    def analyze_interaction_data(flight_id, user_ids=None):
        """Analyze interaction data for insights about the segment"""
        interactions_df = read_s3_csv(BUCKET_NAME, INTERACTIONS_CSV_PATH)
        if interactions_df is None:
            logger.error("Failed to read interactions CSV")
            return None
            
        # Filter interactions for the specified flight
        flight_interactions = interactions_df[interactions_df['ITEM_ID'] == flight_id]
        
        # If user_ids provided, filter further
        if user_ids:
            flight_interactions = flight_interactions[flight_interactions['USER_ID'].isin(user_ids)]
        
        if flight_interactions.empty:
            return None
            
        # Calculate average rating
        avg_rating = flight_interactions['EVENT_VALUE'].mean()
        
        # Count ratings by cabin type
        cabin_counts = flight_interactions.groupby('CABIN_TYPE').size().to_dict()
        
        # Get distribution of ratings
        rating_distribution = flight_interactions['EVENT_VALUE'].value_counts().sort_index().to_dict()
        
        return {
            "averageRating": avg_rating,
            "cabinTypeDistribution": cabin_counts,
            "ratingDistribution": rating_distribution,
            "totalInteractions": len(flight_interactions)
        }
    
    def generate_email_content(event):
        """Generate email content for a specific flight segment"""
        flight_id = get_named_parameter(event, 'flightId', None)
        
        if not flight_id:
            return {
                "status": "error",
                "message": "Missing required parameter: flightId"
            }
        
        # Get flight details
        flight_details = get_flight_details(flight_id)
        
        if not flight_details:
            return {
                "status": "error",
                "message": f"No flight found with ID: {flight_id}"
            }
        
        # Get user segment for this flight
        segments = get_segment_output(BUCKET_NAME)
        segment_users = []
        
        if segments:
            for segment in segments:
                if segment.get('input', {}).get('itemId') == flight_id:
                    segment_users = segment.get('output', {}).get('usersList', [])
                    break
        
        # Get user tier distribution
        users_df = read_s3_csv(BUCKET_NAME, USERS_CSV_PATH)
        tier_distribution = {}
        
        if users_df is not None and segment_users:
            segment_users_df = users_df[users_df['USER_ID'].isin(segment_users)]
            tier_distribution = segment_users_df['MEMBER_TIER'].value_counts().to_dict()
        
        # Get interaction insights
        interaction_insights = analyze_interaction_data(flight_id, segment_users)
        
        # Build email content context
        promotion_code = flight_id[-5:]  # Last 5 chars of flight ID
        
        return {
            "status": "success",
            "flightDetails": {
                "flightId": flight_id,
                "source": flight_details.get('SRC_CITY'),
                "destination": flight_details.get('DST_CITY'),
                "airline": flight_details.get('AIRLINE'),
                "month": flight_details.get('MONTH'),
                "price": flight_details.get('DYNAMIC_PRICE'),
                "duration": flight_details.get('DURATION_DAYS'),
                "promotionCode": promotion_code
            },
            "segmentDetails": {
                "userCount": len(segment_users),
                "userSample": segment_users[:5] if segment_users else [],
                "tierDistribution": tier_distribution
            },
            "interactionInsights": interaction_insights,
            "emailSuggestions": {
                "subjectLine": f"Exclusive Deal: Fly from {flight_details.get('SRC_CITY')} to {flight_details.get('DST_CITY')} this {flight_details.get('MONTH')}!",
                "keyPoints": [
                    f"Promotional price of ${flight_details.get('DYNAMIC_PRICE')}",
                    f"{flight_details.get('DURATION_DAYS')} day trip",
                    f"Operated by {flight_details.get('AIRLINE')}",
                    f"Use promotion code {promotion_code}"
                ]
            }
        }
    
    def generate_multi_flight_email(event):
        """Generate email content for users in multiple segments"""
        flight_ids = get_named_parameter(event, 'flightIds', [])
        
        if not flight_ids:
            return {
                "status": "error",
                "message": "Missing required parameter: flightIds"
            }
        
        # Get segment data
        segments = get_segment_output(BUCKET_NAME)
        if not segments:
            return {
                "status": "warning",
                "message": "No segment data available",
                "flightCount": len(flight_ids)
            }
        
        # Map flight IDs to user lists
        flight_users = {}
        for segment in segments:
            item_id = segment.get('input', {}).get('itemId')
            if item_id in flight_ids:
                users = segment.get('output', {}).get('usersList', [])
                flight_users[item_id] = users
        
        # Find overlapping users
        all_users = {}
        for flight_id, users in flight_users.items():
            for user in users:
                if user not in all_users:
                    all_users[user] = []
                all_users[user].append(flight_id)
        
        overlapping_users = {user: flights for user, flights in all_users.items() if len(flights) > 1}
        
        if not overlapping_users:
            return {
                "status": "warning",
                "message": "No overlapping users found in the selected flight segments",
                "flightCount": len(flight_ids)
            }
        
        # Get flight details
        flight_details = []
        for flight_id in flight_ids:
            flight = get_flight_details(flight_id)
            if flight:
                flight_details.append({
                    "flightId": flight_id,
                    "source": flight.get('SRC_CITY'),
                    "destination": flight.get('DST_CITY'),
                    "airline": flight.get('AIRLINE'),
                    "month": flight.get('MONTH'),
                    "price": flight.get('DYNAMIC_PRICE'),
                    "duration": flight.get('DURATION_DAYS'),
                    "promotionCode": flight_id[-5:]  # Last 5 chars of flight ID
                })
        
        # Get user tier distribution
        users_df = read_s3_csv(BUCKET_NAME, USERS_CSV_PATH)
        tier_distribution = {}
        
        if users_df is not None:
            overlapping_user_ids = list(overlapping_users.keys())
            overlap_users_df = users_df[users_df['USER_ID'].isin(overlapping_user_ids)]
            tier_distribution = overlap_users_df['MEMBER_TIER'].value_counts().to_dict()
        
        return {
            "status": "success",
            "overlappingUsers": len(overlapping_users),
            "userSample": list(overlapping_users.keys())[:5],
            "flights": flight_details,
            "tierDistribution": tier_distribution,
            "emailSuggestions": {
                "subjectLine": "Multiple Exclusive Flight Deals Just For You!",
                "approach": "Highlight all available flight options with a focus on variety and choice"
            }
        }
    
    def save_email_template(event):
        """Save a finalized email template to S3"""
        flight_id = get_named_parameter(event, 'flightId', None)
        email_subject = get_named_parameter(event, 'emailSubject', '')
        email_body = get_named_parameter(event, 'emailBody', '')
        
        if not flight_id or not email_subject or not email_body:
            return {
                "status": "error",
                "message": "Missing required parameters"
            }
        
        try:
            # Get flight details for filename
            flight_details = get_flight_details(flight_id)
            
            if flight_details:
                src = flight_details.get('SRC_CITY', '').replace(' ', '_').lower()
                dst = flight_details.get('DST_CITY', '').replace(' ', '_').lower()
                filename = f"email_template_{src}_to_{dst}_{flight_id[-5:]}.txt"
            else:
                filename = f"email_template_{flight_id[-5:]}.txt"
            
            # Format the email content
            email_content = f"Subject: {email_subject}\n\n{email_body}"
            
            # Save to S3
            s3_path = f"{EMAIL_TEMPLATE_PATH}{filename}"
            success = write_to_s3(BUCKET_NAME, s3_path, email_content)
            
            if success:
                return {
                    "status": "success",
                    "message": "Email template saved successfully",
                    "filename": filename,
                    "s3Path": s3_path,
                    "downloadUrl": f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_path}"
                }
            else:
                return {
                    "status": "error",
                    "message": "Failed to save email template"
                }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Error saving email template: {str(e)}"
            }

    # Process the request based on API path
    result = ''
    response_code = 200
    action_group = event.get('actionGroup', '')
    api_path = event.get('apiPath', '')

    logger.info(f"Processing request: {action_group}::{api_path}")

    try:
        if api_path == '/listAvailableSegments':
            result = list_available_segments(event)
        elif api_path == '/generateEmailContent':
            result = generate_email_content(event)
        elif api_path == '/generateMultiFlightEmail':
            result = generate_multi_flight_email(event)
        elif api_path == '/saveEmailTemplate':
            result = save_email_template(event)
        else:
            response_code = 404
            result = {
                "status": "error",
                "message": f"Unrecognized api path: {action_group}::{api_path}"
            }
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        response_code = 500
        result = {
            "status": "error",
            "message": f"Internal server error: {str(e)}"
        }

    response_body = {
        'application/json': {
            'body': result
        }
    }

    action_response = {
        'actionGroup': event.get('actionGroup', ''),
        'apiPath': event.get('apiPath', ''),
        'httpMethod': event.get('httpMethod', ''),
        'httpStatusCode': response_code,
        'responseBody': response_body
    }

    api_response = {'messageVersion': '1.0', 'response': action_response}
    logger.info(f"Returning response: {json.dumps(api_response)}")
    return api_response