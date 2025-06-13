from office365.runtime.auth.client_credential import ClientCredential
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.files.file import File
from office365.sharepoint.folders.folder import Folder
import whisper
import json
import tempfile
import os
from datetime import datetime
from dotenv import load_dotenv
import re

# Load environment variables
load_dotenv()

class ExistingRecordingProcessor:
    def __init__(self):
        # Initialize SharePoint context
        self.sharepoint_site = os.getenv('SHAREPOINT_SITE_URL')
        self.client_id = os.getenv('SHAREPOINT_CLIENT_ID')
        self.client_secret = os.getenv('SHAREPOINT_CLIENT_SECRET')
        self.ctx = ClientContext(self.sharepoint_site).with_credentials(
            ClientCredential(self.client_id, self.client_secret)
        )
        
        # Initialize Whisper model for transcription
        self.transcription_model = whisper.load_model("base")
        
        # Root folder for all project leads
        self.root_folder = "Shared Documents/ProjectLeads"
        
    def search_recordings_by_phone(self, phone_number, target_lead_folder):
        """
        Search for recordings containing the phone number across all leads
        and copy them to the new lead's folder if found
        """
        try:
            # Format phone number for search (remove special characters)
            search_number = ''.join(filter(str.isdigit, phone_number))
            if len(search_number) == 10:  # Add +1 prefix if 10 digits
                search_patterns = [f"+1{search_number}", search_number]
            else:
                search_patterns = [f"+{search_number}", search_number]
                
            print(f"Searching for recordings with phone numbers: {search_patterns}")
            
            # Get all lead folders
            root = self.ctx.web.get_folder_by_server_relative_url(self.root_folder)
            lead_folders = root.folders
            self.ctx.load(lead_folders)
            self.ctx.execute_query()
            
            recordings_found = []
            
            # Search through each lead folder
            for lead_folder in lead_folders:
                try:
                    # Check RingCentral folder
                    rc_folder_path = f"{lead_folder.properties['ServerRelativeUrl']}/Sources/RingCentral"
                    rc_folder = self.ctx.web.get_folder_by_server_relative_url(rc_folder_path)
                    files = rc_folder.files
                    self.ctx.load(files)
                    self.ctx.execute_query()
                    
                    # Search through recordings and their metadata
                    for file in files:
                        if file.properties['Name'].endswith('.mp3'):
                            # Try to find matching metadata file
                            metadata_path = f"{file.properties['ServerRelativeUrl']}.json"
                            try:
                                metadata_content = File.open_binary(self.ctx, metadata_path)
                                metadata = json.loads(metadata_content.decode('utf-8'))
                                
                                # Check if phone number matches
                                phone_matches = any(
                                    pattern in metadata.get('from', '') or pattern in metadata.get('to', '')
                                    for pattern in search_patterns
                                )
                                
                                if phone_matches:
                                    recording_info = self.process_matching_recording(
                                        file, metadata, target_lead_folder
                                    )
                                    if recording_info:
                                        recordings_found.append(recording_info)
                                        
                            except Exception as e:
                                print(f"Error processing metadata for {file.properties['Name']}: {str(e)}")
                                # If no metadata file, try to extract date from filename
                                filename = file.properties['Name']
                                if any(pattern in filename for pattern in search_patterns):
                                    recording_info = self.process_matching_recording(
                                        file, None, target_lead_folder
                                    )
                                    if recording_info:
                                        recordings_found.append(recording_info)
                    
                except Exception as e:
                    print(f"Error accessing folder {lead_folder.properties['Name']}: {str(e)}")
                    continue
            
            print(f"Found {len(recordings_found)} matching recordings")
            return recordings_found
            
        except Exception as e:
            print(f"Error searching recordings: {str(e)}")
            return []
            
    def process_matching_recording(self, file, existing_metadata, target_lead_folder):
        """Process a matching recording: copy to new location and generate transcript"""
        try:
            # Download the recording
            file_content = File.open_binary(self.ctx, file.properties['ServerRelativeUrl'])
            
            # Generate new filename with timestamp
            original_filename = file.properties['Name']
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if existing_metadata:
                # Use existing metadata to create filename
                direction = existing_metadata.get('direction', 'Unknown')
                duration = existing_metadata.get('duration', 0)
                recording_id = existing_metadata.get('recording_id', 'unknown')
                new_filename = f"call_{timestamp}_{direction}_{duration}sec_{recording_id}.mp3"
            else:
                # Create new filename with original name and timestamp
                new_filename = f"call_{timestamp}_{original_filename}"
            
            # Define target paths
            recordings_folder = f"{target_lead_folder}/Sources/RingCentral"
            transcripts_folder = f"{target_lead_folder}/Transcripts_JSON"
            recording_path = f"{recordings_folder}/{new_filename}"
            
            # Save recording temporarily for transcription
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                temp_file.write(file_content)
                temp_path = temp_file.name
            
            # Transcribe the audio
            print(f"Transcribing {new_filename}...")
            transcript_result = self.transcription_model.transcribe(temp_path)
            
            # Clean up temporary file
            os.unlink(temp_path)
            
            # Prepare transcript data
            transcript_data = {
                "original_file": original_filename,
                "original_location": file.properties['ServerRelativeUrl'],
                "call_metadata": existing_metadata if existing_metadata else {},
                "transcript": {
                    "text": transcript_result["text"],
                    "segments": transcript_result["segments"],
                    "language": transcript_result["language"]
                }
            }
            
            # Upload recording to new location
            File.save_content(self.ctx, recording_path, file_content)
            print(f"Recording copied to: {recording_path}")
            
            # Save transcript
            transcript_filename = f"transcript_{timestamp}_{os.path.splitext(new_filename)[0]}.json"
            transcript_path = f"{transcripts_folder}/{transcript_filename}"
            File.save_content(self.ctx, transcript_path, json.dumps(transcript_data, indent=2))
            print(f"Transcript saved to: {transcript_path}")
            
            return {
                "recording": {
                    "original_file": original_filename,
                    "new_file": new_filename,
                    "new_path": recording_path
                },
                "transcript": {
                    "filename": transcript_filename,
                    "path": transcript_path
                },
                "metadata": transcript_data
            }
            
        except Exception as e:
            print(f"Error processing recording {file.properties['Name']}: {str(e)}")
            return None

def process_existing_lead_recordings(phone_number, lead_folder_path):
    """Main function to process existing recordings for a new lead"""
    processor = ExistingRecordingProcessor()
    recordings = processor.search_recordings_by_phone(phone_number, lead_folder_path)
    return recordings

if __name__ == "__main__":
    # Example usage
    test_phone = "+1234567890"
    test_folder = "/sites/YourSite/Shared Documents/ProjectLeads/Smith_123MainSt"
    recordings = process_existing_lead_recordings(test_phone, test_folder) 