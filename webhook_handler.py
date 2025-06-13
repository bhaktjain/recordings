from ringcentral import SDK
import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv
from office365.runtime.auth.client_credential import ClientCredential
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.files.file import File
from office365.sharepoint.folders.folder import Folder

# Load environment variables
load_dotenv()

class WebhookHandler:
    def __init__(self):
        # Initialize RingCentral SDK
        self.rcsdk = SDK(
            os.getenv('RC_CLIENT_ID'),
            os.getenv('RC_CLIENT_SECRET'),
            os.getenv('RC_SERVER_URL', 'https://platform.ringcentral.com')
        )
        self.platform = self.rcsdk.platform()
        
        # Set the access token
        self.access_token = os.getenv('RC_ACCESS_TOKEN')
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

    def handle_webhook(self, webhook_data):
        """Handle incoming webhook data"""
        try:
            # Parse webhook data
            if isinstance(webhook_data, str):
                data = json.loads(webhook_data)
            else:
                data = webhook_data

            # Check if this is a telephony session notification
            if 'body' in data and 'parties' in data['body']:
                self.process_call_event(data['body'])
            else:
                print("Received non-telephony event:", json.dumps(data, indent=2))

        except Exception as e:
            print(f"Error processing webhook data: {str(e)}")

    def process_call_event(self, call_data):
        """Process a call event and check for recordings"""
        try:
            # Check if call is completed
            if any(party.get('status', {}).get('code') == 'Disconnected' for party in call_data['parties']):
                # Get the phone numbers involved in the call
                phone_numbers = self.extract_phone_numbers(call_data)
                
                if phone_numbers:
                    # Wait for recording and transcript to be ready
                    session_id = call_data.get('sessionId')
                    if session_id:
                        print(f"Call completed (Session ID: {session_id})")
                        self.process_recording(session_id, phone_numbers)

        except Exception as e:
            print(f"Error processing call event: {str(e)}")

    def extract_phone_numbers(self, call_data):
        """Extract all phone numbers from the call data"""
        phone_numbers = set()
        
        # Get numbers from parties
        for party in call_data.get('parties', []):
            if 'from' in party and 'phoneNumber' in party['from']:
                phone_numbers.add(party['from']['phoneNumber'])
            if 'to' in party and 'phoneNumber' in party['to']:
                phone_numbers.add(party['to']['phoneNumber'])

        return list(phone_numbers)

    def find_lead_folders(self, phone_number):
        """Find all lead folders that have this phone number in their records"""
        try:
            # Get the ProjectLeads folder
            root = self.ctx.web.get_folder_by_server_relative_url("Shared Documents/ProjectLeads")
            folders = root.folders
            self.ctx.load(folders)
            self.ctx.execute_query()
            
            matching_folders = []
            
            # Search through each lead folder
            for folder in folders:
                try:
                    # Check if there's a matching record in Transcripts_JSON
                    transcripts_path = f"{folder.properties['ServerRelativeUrl']}/Transcripts_JSON"
                    transcripts_folder = self.ctx.web.get_folder_by_server_relative_url(transcripts_path)
                    files = transcripts_folder.files
                    self.ctx.load(files)
                    self.ctx.execute_query()
                    
                    # Check each transcript file
                    for file in files:
                        if file.properties['Name'].endswith('.json'):
                            content = File.open_binary(self.ctx, file.properties['ServerRelativeUrl'])
                            transcript_data = json.loads(content.decode('utf-8'))
                            
                            # Check if phone number matches
                            call_metadata = transcript_data.get('call_metadata', {})
                            if (phone_number == call_metadata.get('from') or 
                                phone_number == call_metadata.get('to')):
                                matching_folders.append(folder.properties['ServerRelativeUrl'])
                                break
                    
                except Exception as e:
                    print(f"Error checking folder {folder.properties['Name']}: {str(e)}")
                    continue
            
            return matching_folders
            
        except Exception as e:
            print(f"Error searching for lead folders: {str(e)}")
            return []

    def process_recording(self, session_id, phone_numbers):
        """Process recording and save to appropriate lead folders"""
        try:
            # Wait a moment for recording to be ready
            import time
            time.sleep(5)
            
            # Get call recording details
            recording_response = self.platform.get(f'/restapi/v1.0/account/~/call-recordings/{session_id}')
            recording_data = recording_response.json()
            
            if recording_data.get('status') != 'Available':
                print(f"Recording not yet available for session {session_id}")
                return
            
            # Get RingSense transcript
            transcript_response = self.platform.get(
                f'/restapi/v1.0/account/~/call-recordings/{session_id}/ringsense'
            )
            transcript_data = transcript_response.json()
            
            # Find all matching lead folders
            matching_folders = []
            for phone in phone_numbers:
                folders = self.find_lead_folders(phone)
                matching_folders.extend(folders)
            
            # Remove duplicates
            matching_folders = list(set(matching_folders))
            
            if not matching_folders:
                print(f"No matching lead folders found for phone numbers: {phone_numbers}")
                return
            
            # Save transcript to each matching folder
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            for folder_path in matching_folders:
                try:
                    # Prepare transcript data
                    transcript = {
                        'recording_id': session_id,
                        'call_metadata': {
                            'direction': recording_data.get('direction'),
                            'duration': recording_data.get('duration'),
                            'start_time': recording_data.get('startTime'),
                            'end_time': recording_data.get('endTime'),
                            'from': recording_data.get('from', {}).get('phoneNumber'),
                            'to': recording_data.get('to', {}).get('phoneNumber')
                        },
                        'transcript': transcript_data
                    }
                    
                    # Save transcript
                    transcript_filename = f"transcript_{timestamp}_{session_id}.json"
                    transcript_path = f"{folder_path}/Transcripts_JSON/{transcript_filename}"
                    
                    File.save_content(
                        self.ctx,
                        transcript_path,
                        json.dumps(transcript, indent=2)
                    )
                    print(f"Saved transcript to {transcript_path}")
                    
                except Exception as e:
                    print(f"Error saving to folder {folder_path}: {str(e)}")
                    continue
            
        except Exception as e:
            print(f"Error processing recording: {str(e)}")

def handle_new_recording(webhook_data):
    """Main function to handle new recording webhook"""
    handler = WebhookHandler()
    handler.handle_webhook(webhook_data)

if __name__ == "__main__":
    # Example webhook data for testing
    test_data = {
        "body": {
            "sessionId": "12345",
            "parties": [
                {
                    "from": {"phoneNumber": "+1234567890"},
                    "to": {"phoneNumber": "+0987654321"},
                    "status": {"code": "Disconnected"}
                }
            ]
        }
    }
    handle_new_recording(test_data) 