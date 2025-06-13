import azure.functions as func
import logging
import json
from ringcentral import SDK
import os
from datetime import datetime, timedelta
from office365.runtime.auth.client_credential import ClientCredential
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.files.file import File

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    try:
        # Get request body
        req_body = req.get_json()
        phone_number = req_body.get('phone_number')
        folder_path = req_body.get('folder_path')

        if not phone_number or not folder_path:
            return func.HttpResponse(
                "Please pass phone_number and folder_path in the request body",
                status_code=400
            )

        # Initialize RingCentral SDK
        rcsdk = SDK(
            os.environ["RC_CLIENT_ID"],
            os.environ["RC_CLIENT_SECRET"],
            os.environ["RC_SERVER_URL"]
        )
        platform = rcsdk.platform()
        
        # Authenticate using JWT
        try:
            platform.auth().set_data({
                'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                'assertion': os.environ["RC_JWT_TOKEN"]
            })
        except Exception as auth_error:
            logging.error(f"RingCentral authentication error: {str(auth_error)}")
            return func.HttpResponse(
                f"RingCentral authentication failed: {str(auth_error)}",
                status_code=401
            )

        # Initialize SharePoint client
        try:
            ctx = ClientContext(os.environ["SHAREPOINT_SITE_URL"]).with_client_credentials(
                os.environ["SHAREPOINT_CLIENT_ID"],
                os.environ["SHAREPOINT_CLIENT_SECRET"]
            )
        except Exception as sp_error:
            logging.error(f"SharePoint authentication error: {str(sp_error)}")
            return func.HttpResponse(
                f"SharePoint authentication failed: {str(sp_error)}",
                status_code=401
            )

        # Format phone number
        formatted_phone = format_phone_number(phone_number)
        
        # Get call recordings
        response = platform.get('/restapi/v1.0/account/~/call-log', {
            'type': 'Voice',
            'phoneNumber': formatted_phone,
            'view': 'Detailed',
            'dateFrom': (datetime.now() - timedelta(days=30)).isoformat() + 'Z'
        })
        
        calls = response.json().get('records', [])
        logging.info(f'Found {len(calls)} calls for {phone_number}')
        
        processed_recordings = []
        
        for call in calls:
            # Check if call has recording
            if call.get('recording') and call.get('recording').get('id'):
                recording_id = call['recording']['id']
                try:
                    # Get RingSense transcript
                    transcript_response = platform.get(
                        f'/restapi/v1.0/account/~/call-recordings/{recording_id}/ringsense'
                    )
                    transcript_data = transcript_response.json()
                    
                    # Prepare transcript with metadata
                    transcript = {
                        'recording_id': recording_id,
                        'call_metadata': {
                            'direction': call.get('direction'),
                            'duration': call.get('duration'),
                            'start_time': call.get('startTime'),
                            'end_time': call.get('endTime'),
                            'from': call.get('from', {}).get('phoneNumber'),
                            'to': call.get('to', {}).get('phoneNumber')
                        },
                        'transcript': transcript_data
                    }
                    
                    # Generate filename
                    timestamp = datetime.fromisoformat(
                        call['startTime'].replace('Z', '+00:00')
                    ).strftime('%Y%m%d_%H%M%S')
                    
                    filename = f"transcript_{timestamp}_{recording_id}.json"
                    file_path = f"{folder_path}/Transcripts_JSON/{filename}"
                    
                    # Save to SharePoint
                    File.save_content(
                        ctx,
                        file_path,
                        json.dumps(transcript, indent=2)
                    )
                    
                    processed_recordings.append({
                        'recording_id': recording_id,
                        'transcript_path': file_path
                    })
                    
                    logging.info(f'Processed recording {recording_id}')
                    
                except Exception as e:
                    logging.error(f'Error processing recording {recording_id}: {str(e)}')
                    continue
        
        return func.HttpResponse(
            json.dumps({
                'status': 'success',
                'processed_recordings': processed_recordings
            }),
            mimetype="application/json"
        )
        
    except Exception as e:
        logging.error(f'Error: {str(e)}')
        return func.HttpResponse(
            f"An error occurred: {str(e)}",
            status_code=500
        )

def format_phone_number(phone):
    """Format phone number to E.164 format"""
    digits = ''.join(filter(str.isdigit, phone))
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith('1'):
        return f"+{digits}"
    return f"+{digits}" 