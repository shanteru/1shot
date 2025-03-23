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

    def list_promotional_flights(event):
        """List all promotional flights available for email campaigns"""
        month_filter = get_named_parameter(event, 'month', None)
        destination_filter = get_named_parameter(event, 'destination', None)
        
        items_df = read_s3_csv(BUCKET_NAME, ITEMS_CSV_PATH)
        if items_df is None:
            return {"error": "Failed to load flight data"}
        
        # Get all promotional flights that are not expired
        promo_flights = items_df[(items_df['PROMOTION'] == 'Yes') & (items_df['EXPIRED'] != 'Yes')]
        
        # Apply filters if provided
        if month_filter:
            promo_flights = promo_flights[promo_flights['MONTH'].str.lower() == month_filter.lower()]
        
        if destination_filter:
            promo_flights = promo_flights[promo_flights['DST_CITY'].str.lower() == destination_filter.lower()]
        
        # Get segments to show which flights have user segments available
        segments = read_s3_json(BUCKET_NAME, SEGMENT_OUTPUT_PATH)
        segment_item_ids = []
        
        if segments:
            segment_item_ids = [segment.get('input', {}).get('itemId') for segment in segments]
        
        # Prepare results
        results = []
        for _, flight in promo_flights.iterrows():
            flight_data = {
                "itemId": flight.get('ITEM_ID'),
                "source": flight.get('SRC_CITY'),
                "destination": flight.get('DST_CITY'),
                "airline": flight.get('AIRLINE'),
                "month": flight.get('MONTH'),
                "price": flight.get('DYNAMIC_PRICE'),
                "duration": flight.get('DURATION_DAYS'),
                "hasSegment": flight.get('ITEM_ID') in segment_item_ids
            }
            results.append(flight_data)
        
        return {
            "flights": results,
            "totalCount": len(results),
            "monthOptions": sorted(promo_flights['MONTH'].unique().tolist()),
            "destinationOptions": sorted(promo_flights['DST_CITY'].unique().tolist())
        }
    
    def prepare_segment_input(event):
        """Format flight IDs into proper JSON structure for batch segmentation"""
        flight_ids = get_named_parameter(event, 'flightIds', [])
        
        if not flight_ids:
            return {
                "status": "error",
                "message": "Missing required parameter: flightIds"
            }
            
        try:
            # Format each flight ID into the required JSON format
            lines = []
            for flight_id in flight_ids:
                lines.append(json.dumps({"itemId": flight_id}))
            
            # Join with newlines
            content = "\n".join(lines)
            
            # Generate JSON file content for download
            return {
                "status": "success",
                "message": f"Created JSON input for {len(flight_ids)} flights",
                "jsonContent": content,
                "flightCount": len(flight_ids),
                "instructions": "Download this file and send it to your data team for batch segment job processing"
            }
        except Exception as e:
            logger.error(f"Error preparing segment input: {str(e)}")
            return {
                "status": "error",
                "message": f"Error: {str(e)}"
            }

    # Process the request based on API path
    result = ''
    response_code = 200
    action_group = event.get('actionGroup', '')
    api_path = event.get('apiPath', '')

    logger.info(f"Processing request: {action_group}::{api_path}")

    try:
        if api_path == '/listPromotionalFlights':
            result = list_promotional_flights(event)
        elif api_path == '/prepareSegmentInput':
            result = prepare_segment_input(event)
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