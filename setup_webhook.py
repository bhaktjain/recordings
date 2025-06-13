from ringcentral import SDK
import os
from dotenv import load_dotenv
import uuid
import requests
import time
import secrets
import string
import json

# Load environment variables
load_dotenv()

def generate_verification_token(length=32):
    """Generate a simple verification token that RingCentral accepts"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def test_webhook_validation(webhook_url, validation_token):
    """Test if the webhook endpoint correctly echoes back the validation token"""
    headers = {
        'Content-Type': 'application/json',  # RingCentral uses application/json for validation
        'Accept': 'text/plain',
        'User-Agent': 'RingCentral-Webhook-v1',
        'Validation-Token': validation_token  # Use uppercase as per RingCentral docs
    }
    
    try:
        print(f"\nSending validation request with token: {validation_token}")
        # Send a test validation request to Power Automate
        response = requests.post(webhook_url, headers=headers)
        print(f"Validation response status: {response.status_code}")
        print(f"Validation response body: {response.text}")
        print(f"Validation response headers: {response.headers}")
        
        if response.status_code == 200:
            # Check both body and headers for the validation token
            response_token_body = response.text.strip()
            response_token_header = response.headers.get('Validation-Token')  # Try uppercase first
            if not response_token_header:
                response_token_header = response.headers.get('validation-token')  # Try lowercase as fallback
            
            print(f"Response token in body: {response_token_body}")
            print(f"Response token in header: {response_token_header}")
            
            # RingCentral expects the token in the Validation-Token header
            if response_token_header == validation_token:
                print("Webhook validation successful! (via header)")
                return True
            elif response_token_body == validation_token:
                print("Warning: Token found in body but not in header - RingCentral expects it in the header")
                return False
            else:
                print(f"Token mismatch. Expected: {validation_token}")
                print(f"Got in body: {response_token_body}")
                print(f"Got in header: {response_token_header}")
                return False
    except Exception as e:
        print(f"Webhook validation test failed: {str(e)}")
        return False

def setup_webhook():
    try:
        # Initialize the SDK
        rcsdk = SDK(
            os.getenv('RC_CLIENT_ID'),
            os.getenv('RC_CLIENT_SECRET'),
            os.getenv('RC_SERVER_URL', 'https://platform.ringcentral.com')
        )
        platform = rcsdk.platform()
        
        # Set the access token directly
        access_token = 'SUFENDFQMTRQQVMwMHxBQUM1QlEzd1QxTDdfTEVmWENUNkRkanM1bjJPRE96cFFJQjRWNWc3SXA0S21Gb1p0UGRzc3ZjTXNiaFlLVlJVTEJST2J5YWIxd2JjTXpWNDZTdG5qNENabGZRNUNWSk5Mblk4NnhXSDRIZU1JLXJZRURGWmRQQ3Z0NHZxbkpCN0JaRUpYdDhobmlHdEEwNl96a0l3dHYwaUh6WGs5NlNFWGpGd1RiRUJPWEFDeEcyUjZCcF9XNTk0ZWlmTlBuYVBfN01ES3VZbk1qSUZnSTBfeVFDLURDbTZKMjc1UHd8SnY0T19BfDFUVzJnOEdjXzE3TGp6U0hTMHA1ZVF8QVF8QUF8QUFBQUFPLVlmWkE'
        platform.auth().set_data({
            'access_token': access_token,
            'token_type': 'bearer',
            'expires_in': 3600,
            'scope': 'ReadContacts SubscriptionWebSocket ReadAccounts RingSense ReadCallLog ReadCallRecording SubscriptionWebhook Analytics WebSocket'
        })
        
        # Generate tokens - use a simpler format for validation token
        validation_token = generate_verification_token()  # Use same format for both tokens
        verification_token = generate_verification_token()
        print(f"Generated validation token: {validation_token}")
        print(f"Generated verification token: {verification_token}")
        
        # Test if the webhook endpoint validates correctly
        webhook_url = os.getenv('POWER_AUTOMATE_WEBHOOK_URL')
        if not test_webhook_validation(webhook_url, validation_token):
            print("Error: Webhook endpoint failed validation test")
            print("Please ensure your Power Automate flow:")
            print("1. Returns the validation token in the 'Validation-Token' header")
            print("2. Sets Content-Type to 'text/plain; charset=utf-8'")
            print("3. Returns the exact token without any modifications")
            return
            
        # Wait a moment to ensure Power Automate is ready
        time.sleep(5)  # Increased wait time
        
        # Create webhook subscription with verification token - using requests directly
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'User-Agent': 'RingCentral-Webhook-v1'
        }
        
        data = {
            'eventFilters': [
                '/restapi/v1.0/account/~/telephony/sessions',
                '/restapi/v1.0/account/~/extension/~/telephony/sessions'
            ],
            'deliveryMode': {
                'transportType': 'WebHook',
                'address': webhook_url,
                'verificationToken': verification_token,
                'validationToken': validation_token
            },
            'expiresIn': 630720000  # Set to maximum allowed (about 7 days)
        }
        
        # Send the subscription request
        resp = requests.post(
            'https://platform.ringcentral.com/restapi/v1.0/subscription',
            headers=headers,
            json=data  # Use json parameter to automatically set correct Content-Type
        )
        
        if resp.status_code == 200:
            print("Webhook setup successful!")
            print("Response:", resp.json())
        else:
            print(f"Error: HTTP {resp.status_code} {resp.text}")
        
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    setup_webhook() 