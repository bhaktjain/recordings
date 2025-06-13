from ringcentral import SDK
import os
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time
from office365.runtime.auth.client_credential import ClientCredential
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.files.file import File
import whisper
import tempfile

# Load environment variables
load_dotenv()

class CallRecordingProcessor:
    def __init__(self):
        self.rcsdk = SDK(
            os.getenv('RC_CLIENT_ID'),
            os.getenv('RC_CLIENT_SECRET'),
            os.getenv('RC_SERVER_URL', 'https://platform.ringcentral.com')
        )
        self.platform = self.rcsdk.platform()
        
        # Set the access token
        self.access_token = 'SUFENDFQMTRQQVMwMHxBQUM1QlEzd1QxTDdfTEVmWENUNkRkanM1bjJPRE96cFFJQjRWNWc3SXA0S21Gb1p0UGRzc3ZjTXNiaFlLVlJVTEJST2J5YWIxd2JjTXpWNDZTdG5qNENabGZRNUNWSk5Mblk4NnhXSDRIZU1JLXJZRURGWmRQQ3Z0NHZxbkpCN0JaRUpYdDhobmlHdEEwNl96a0l3dHYwaUh6WGs5NlNFWGpGd1RiRUJPWEFDeEcyUjZCcF9XNTk0ZWlmTlBuYVBfN01ES3VZbk1qSUZnSTBfeVFDLURDbTZKMjc1UHd8SnY0T19BfDFUVzJnOEdjXzE3TGp6U0hTMHA1ZVF8QVF8QUF8QUFBQUFPLVlmWkE'
        self.platform.auth().set_data({
            'access_token': self.access_token,
            'token_type': 'bearer',
            'expires_in': 3600,
            'scope': 'ReadContacts SubscriptionWebSocket ReadAccounts RingSense ReadCallLog ReadCallRecording SubscriptionWebhook Analytics WebSocket'
        })
        
        # Initialize SharePoint context
        self.sharepoint_site = os.getenv('SHAREPOINT_SITE_URL')
        self.client_id = os.getenv('SHAREPOINT_CLIENT_ID')
        self.client_secret = os.getenv('SHAREPOINT_CLIENT_SECRET')
        self.ctx = ClientContext(self.sharepoint_site).with_credentials(
            ClientCredential(self.client_id, self.client_secret)
        )
        
        # Initialize Whisper model for transcription
        self.transcription_model = whisper.load_model("base")

    def search_recordings_by_phone(self, phone_number, lead_folder_path):
        """Search for call recordings by phone number and save to SharePoint"""
        try:
            # Format phone number to E.164 format if needed
            formatted_phone = self.format_phone_number(phone_number)
            
            # Get call log records with recordings for this phone number
            response = self.platform.get('/restapi/v1.0/account/~/call-log', {
                'type': 'Voice',
                'withRecording': True,
                'phoneNumber': formatted_phone,
                'view': 'Detailed',
                'dateFrom': (datetime.now() - timedelta(days=30)).isoformat() + 'Z'  # Last 30 days
            })
            
            # Parse the response
            data = response.json()
            if isinstance(data, dict):
                calls = data.get('records', [])
            else:
                calls = []
                
            print(f"Found {len(calls)} calls with recordings for phone number {phone_number}")
            
            recordings_found = []
            for call in calls:
                if isinstance(call, dict) and call.get('recording'):
                    recording = call['recording']
                    recording_id = recording.get('id')
                    if recording_id:
                        print(f"Processing recording ID: {recording_id}")
                        
                        # Get recording metadata
                        recording_response = self.platform.get(f'/restapi/v1.0/account/~/recording/{recording_id}')
                        recording_data = recording_response.json()
                        
                        # Download and upload if available
                        if recording_data.get('status') == 'Available':
                            content_uri = recording_data.get('contentUri')
                            if content_uri:
                                recording_info = self.process_recording(
                                    content_uri, 
                                    recording_id, 
                                    recording_data,
                                    lead_folder_path,
                                    call
                                )
                                if recording_info:
                                    recordings_found.append(recording_info)
                            else:
                                print(f"No content URI found for recording {recording_id}")
                        else:
                            status = recording_data.get('status', 'Unknown')
                            print(f"Recording {recording_id} not yet available. Status: {status}")
            
            return recordings_found

        except Exception as e:
            print(f"Error searching recordings by phone: {str(e)}")
            return []

    def process_recording(self, content_uri, recording_id, recording_data, lead_folder_path, call_data):
        """Download recording, transcribe, and upload to SharePoint"""
        try:
            # Get recording content
            response = requests.get(
                content_uri,
                headers={'Authorization': f'Bearer {self.access_token}'},
                stream=True
            )
            
            if response.status_code == 200:
                # Generate filename with call details
                call_date = datetime.fromisoformat(call_data.get('startTime', '').replace('Z', '+00:00'))
                date_str = call_date.strftime('%Y%m%d_%H%M%S')
                direction = call_data.get('direction', 'Unknown')
                duration = call_data.get('duration', 0)
                filename = f"call_{date_str}_{direction}_{duration}sec_{recording_id}.mp3"
                
                # Define folder paths
                recordings_folder = f"{lead_folder_path}/Sources/RingCentral"
                transcripts_folder = f"{lead_folder_path}/Transcripts_JSON"
                
                try:
                    # Save recording temporarily for transcription
                    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                        temp_file.write(response.content)
                        temp_path = temp_file.name
                    
                    # Transcribe the audio
                    print("Transcribing audio...")
                    transcript_result = self.transcription_model.transcribe(temp_path)
                    
                    # Clean up temporary file
                    os.unlink(temp_path)
                    
                    # Prepare transcript data
                    transcript_data = {
                        "recording_id": recording_id,
                        "call_metadata": {
                            "direction": direction,
                            "duration": duration,
                            "start_time": call_data.get('startTime'),
                            "end_time": call_data.get('endTime'),
                            "from": call_data.get('from', {}).get('phoneNumber'),
                            "to": call_data.get('to', {}).get('phoneNumber')
                        },
                        "transcript": {
                            "text": transcript_result["text"],
                            "segments": transcript_result["segments"],
                            "language": transcript_result["language"]
                        }
                    }
                    
                    # Upload recording to SharePoint
                    recording_path = f"{recordings_folder}/{filename}"
                    File.save_content(self.ctx, recording_path, response.content)
                    print(f"Recording uploaded to SharePoint: {recording_path}")
                    
                    # Upload transcript to SharePoint
                    transcript_filename = f"transcript_{date_str}_{recording_id}.json"
                    transcript_path = f"{transcripts_folder}/{transcript_filename}"
                    File.save_content(self.ctx, transcript_path, json.dumps(transcript_data, indent=2))
                    print(f"Transcript uploaded to SharePoint: {transcript_path}")
                    
                    return {
                        "recording": {
                            "filename": filename,
                            "path": recording_path
                        },
                        "transcript": {
                            "filename": transcript_filename,
                            "path": transcript_path
                        },
                        "metadata": transcript_data
                    }
                    
                except Exception as e:
                    print(f"Error processing and uploading files: {str(e)}")
                    return None
                
            else:
                print(f"Failed to download recording {recording_id}. Status code: {response.status_code}")
                return None

        except Exception as e:
            print(f"Error processing recording: {str(e)}")
            return None

    @staticmethod
    def format_phone_number(phone):
        """Format phone number to E.164 format"""
        # Remove any non-digit characters
        digits = ''.join(filter(str.isdigit, phone))
        
        # If it's a 10-digit number, assume US and add +1
        if len(digits) == 10:
            return f"+1{digits}"
        # If it already has country code (11 digits starting with 1)
        elif len(digits) == 11 and digits.startswith('1'):
            return f"+{digits}"
        # Otherwise return as is with + prefix
        return f"+{digits}"

def process_lead_recordings(phone_number, lead_folder_path):
    """Main function to process recordings for a new lead"""
    processor = CallRecordingProcessor()
    recordings = processor.search_recordings_by_phone(phone_number, lead_folder_path)
    return recordings

if __name__ == "__main__":
    # Example usage
    test_phone = "+1234567890"
    test_folder = "/sites/YourSite/Shared Documents/ProjectLeads/Smith_123MainSt"
    recordings = process_lead_recordings(test_phone, test_folder) 