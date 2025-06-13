import requests
import base64
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_access_token():
    # RingCentral API endpoint for token
    token_url = "https://platform.ringcentral.com/restapi/oauth/token"
    
    # Create basic auth header using client_id and client_secret
    credentials = f"{os.getenv('RC_CLIENT_ID')}:{os.getenv('RC_CLIENT_SECRET')}"
    basic_auth = base64.b64encode(credentials.encode()).decode()
    
    # Headers
    headers = {
        "Authorization": f"Basic {basic_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    # Request body
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": os.getenv('RC_JWT_TOKEN')
    }
    
    try:
        # Make the request
        response = requests.post(token_url, headers=headers, data=data)
        
        # Check if request was successful
        if response.status_code == 200:
            print("Access token received successfully!")
            print("\nResponse:")
            print(response.json())
            return response.json().get('access_token')
        else:
            print(f"Error getting access token. Status code: {response.status_code}")
            print("Error message:", response.text)
            return None
            
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return None

if __name__ == "__main__":
    get_access_token() 