from ringcentral import SDK
import os
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from office365.runtime.auth.client_credential import ClientCredential
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.files.file import File

# Load environment variables
load_dotenv()

class LeadProcessor:
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

    def create_folder_structure(self, address_lastName):
        """Create the required folder structure in SharePoint"""
        try:
            base_path = f"Shared Documents/ProjectLeads/{address_lastName}"
            
            # Create main folder
            self.ensure_folder_exists(base_path)
            
            # Create subfolders
            subfolders = [
                "Sources/RingCentral",
                "Sources/Walkthroughs",
                "Sources/ProposalCalls",
                "Sources/Polycam",
                "Transcripts_JSON",
                "AI_Outputs/Pre-Walk_Report",
                "AI_Outputs/Estimates",
                "AI_Outputs/Scope_JSON",
                "AI_Outputs/Moodboards",
                "AI_Outputs/Decks"
            ]
            
            for subfolder in subfolders:
                folder_path = f"{base_path}/{subfolder}"
                self.ensure_folder_exists(folder_path)
            
            print(f"Created folder structure for {address_lastName}")
            return base_path
            
        except Exception as e:
            print(f"Error creating folder structure: {str(e)}")
            return None

    def ensure_folder_exists(self, folder_path):
        """Create a folder if it doesn't exist"""
        try:
            folder = self.ctx.web.ensure_folder_path(folder_path).execute_query()
            return folder
        except Exception as e:
            print(f"Error creating folder {folder_path}: {str(e)}")
            return None

    def get_ringsense_transcripts(self, phone_number, days_back=30):
        """Get RingSense transcripts for a phone number"""
        try:
            # Format phone number to E.164 format
            formatted_phone = self.format_phone_number(phone_number)
            
            # Get call recordings with transcripts
            response = self.platform.get('/restapi/v1.0/account/~/call-log', {
                'type': 'Voice',
                'phoneNumber': formatted_phone,
                'view': 'Detailed',
                'dateFrom': (datetime.now() - timedelta(days=days_back)).isoformat() + 'Z'
            })
            
            calls = response.json().get('records', [])
            print(f"Found {len(calls)} calls for {phone_number}")
            
            transcripts = []
            for call in calls:
                # Get RingSense transcript if available
                if call.get('recording') and call.get('recording').get('id'):
                    recording_id = call['recording']['id']
                    try:
                        transcript_response = self.platform.get(
                            f'/restapi/v1.0/account/~/call-recordings/{recording_id}/ringsense'
                        )
                        transcript_data = transcript_response.json()
                        
                        # Add call metadata to transcript
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
                        transcripts.append(transcript)
                        
                    except Exception as e:
                        print(f"Error getting transcript for recording {recording_id}: {str(e)}")
            
            return transcripts
            
        except Exception as e:
            print(f"Error getting RingSense transcripts: {str(e)}")
            return []

    def save_transcripts(self, transcripts, lead_folder_path):
        """Save transcripts to SharePoint"""
        try:
            transcripts_folder = f"{lead_folder_path}/Transcripts_JSON"
            
            for transcript in transcripts:
                # Generate filename with timestamp and call details
                timestamp = datetime.fromisoformat(
                    transcript['call_metadata']['start_time'].replace('Z', '+00:00')
                ).strftime('%Y%m%d_%H%M%S')
                
                recording_id = transcript['recording_id']
                direction = transcript['call_metadata']['direction']
                
                filename = f"transcript_{timestamp}_{direction}_{recording_id}.json"
                file_path = f"{transcripts_folder}/{filename}"
                
                # Save transcript
                File.save_content(
                    self.ctx,
                    file_path,
                    json.dumps(transcript, indent=2)
                )
                print(f"Saved transcript: {file_path}")
            
        except Exception as e:
            print(f"Error saving transcripts: {str(e)}")

    @staticmethod
    def format_phone_number(phone):
        """Format phone number to E.164 format"""
        digits = ''.join(filter(str.isdigit, phone))
        if len(digits) == 10:
            return f"+1{digits}"
        elif len(digits) == 11 and digits.startswith('1'):
            return f"+{digits}"
        return f"+{digits}"

def process_new_lead(address_lastName, phone_number):
    """Process a new lead: create folders and get transcripts"""
    processor = LeadProcessor()
    
    # Create folder structure
    lead_folder_path = processor.create_folder_structure(address_lastName)
    if not lead_folder_path:
        return None
    
    # Get and save transcripts
    transcripts = processor.get_ringsense_transcripts(phone_number)
    if transcripts:
        processor.save_transcripts(transcripts, lead_folder_path)
    
    return {
        'folder_path': lead_folder_path,
        'transcripts_count': len(transcripts)
    }

if __name__ == "__main__":
    # Example usage
    test_address_lastName = "123MainSt_Smith"
    test_phone = "+1234567890"
    result = process_new_lead(test_address_lastName, test_phone) 