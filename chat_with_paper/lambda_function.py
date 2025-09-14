import json
import os
import hashlib
import boto3
from typing import Dict, Any, List
from google import genai

# Import shared modules
from llm import chat_answer

# Initialize AWS clients
SECRET_NAME = os.environ.get("GEMINI_SECRET_NAME", "prod/gemini/api_key")
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-2.5-flash")
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")

_API_KEY_CACHE = None
_CLIENT_CACHE = None

# Cache directories in Lambda ephemeral storage
CACHE_DIR = "/tmp/paper_cache"
CHAT_DIR = "/tmp/chat_cache"


def _get_api_key():
    """Fetch and cache the API key from Secrets Manager."""
    global _API_KEY_CACHE
    if _API_KEY_CACHE:
        return _API_KEY_CACHE

    try:
        sm = boto3.client("secretsmanager", region_name=REGION)
        print(f"Fetching secret: {SECRET_NAME} from region: {REGION}")
        sec = sm.get_secret_value(SecretId=SECRET_NAME)
        s = sec["SecretString"]
        print(f"Secret fetched successfully, length: {len(s) if s else 0}")

        # Support either a bare string or a simple JSON structure
        try:
            data = json.loads(s)
            print(f"Secret is JSON with keys: {list(data.keys()) if data else []}")
            api_key = data.get("GEMINI_API_KEY") or next(iter(data.values()))
        except Exception as json_error:
            print(f"Secret is not JSON, using as plain string: {type(json_error).__name__}")
            api_key = s

        if not api_key:
            raise ValueError("API key is empty")
            
        _API_KEY_CACHE = api_key.strip()
        
        # Set the environment variable so llm.py can use it
        os.environ["GEMINI_API_KEY"] = _API_KEY_CACHE
        print(f"API key cached successfully, length: {len(_API_KEY_CACHE)}")
        
        return _API_KEY_CACHE
        
    except Exception as e:
        print(f"Error fetching API key: {str(e)}")
        raise


def _get_client():
    global _CLIENT_CACHE
    if _CLIENT_CACHE:
        return _CLIENT_CACHE
    
    # Ensure API key is set in environment
    api_key = _get_api_key()
    _CLIENT_CACHE = genai.Client(api_key=api_key)
    return _CLIENT_CACHE


def get_cached_paper(url: str) -> Dict[str, Any] | None:
    """Retrieve cached paper data from ephemeral storage"""
    cache_key = hashlib.md5(url.encode()).hexdigest()
    cache_file = f"{CACHE_DIR}/{cache_key}.json"
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    
    return None


def get_chat_history(session_id: str, url: str) -> List[Dict[str, str]]:
    """Retrieve chat history from ephemeral storage"""
    os.makedirs(CHAT_DIR, exist_ok=True)
    chat_key = hashlib.md5(f"{session_id}:{url}".encode()).hexdigest()
    chat_file = f"{CHAT_DIR}/{chat_key}.json"
    
    if os.path.exists(chat_file):
        try:
            with open(chat_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    
    return []


def save_chat_history(session_id: str, url: str, history: List[Dict[str, str]]) -> None:
    """Save chat history to ephemeral storage"""
    os.makedirs(CHAT_DIR, exist_ok=True)
    chat_key = hashlib.md5(f"{session_id}:{url}".encode()).hexdigest()
    chat_file = f"{CHAT_DIR}/{chat_key}.json"
    
    with open(chat_file, 'w', encoding='utf-8') as f:
        json.dump(history, f)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda handler for chat functionality"""
    
    # Set up CORS headers
    headers = {
        # 'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'POST, OPTIONS'
    }
    
    # Handle OPTIONS request for CORS preflight
    if event.get('httpMethod') == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': headers,
            'body': ''
        }
    
    try:
        # Parse request body
        if 'body' in event:
            if isinstance(event['body'], str):
                body = json.loads(event['body'])
            else:
                body = event['body']
        else:
            return {
                'statusCode': 400,
                'headers': headers,
                'body': json.dumps({'error': 'Missing request body'})
            }
        
        # Extract parameters
        url = body.get('paper_url', '').strip()
        message = body.get('message', '').strip()
        session_id = body.get('session_id', '')
        
        # Validate inputs
        if not url or not message:
            return {
                'statusCode': 400,
                'headers': headers,
                'body': json.dumps({'error': 'Missing paper_url or message'})
            }
        
        if not session_id:
            return {
                'statusCode': 400,
                'headers': headers,
                'body': json.dumps({'error': 'Missing session_id'})
            }
        
        # Set Gemini API key from Secrets Manager
        try:
            # Initialize client and ensure API key is available
            client = _get_client()
            
            # Also set the model name if provided
            if MODEL_NAME:
                os.environ["GEMINI_MODEL"] = MODEL_NAME
                
        except Exception as e:
            print(f"Error initializing Gemini client: {str(e)}")
            return {
                'statusCode': 500,
                'headers': headers,
                'body': json.dumps({'error': f'Failed to initialize Gemini client: {str(e)}'})
            }
        
        # Check if paper is cached
        cached_paper = get_cached_paper(url)
        if not cached_paper:
            return {
                'statusCode': 400,
                'headers': headers,
                'body': json.dumps({'error': 'Please summarize the paper first'})
            }
        
        # Get chat history
        history = get_chat_history(session_id, url)
        
        # Add user message to history
        history.append({"role": "user", "text": message})
        
        try:
            # Generate response using LLM
            text_context = cached_paper["text"]
            answer = chat_answer(text_context, history)
            
            # Add model response to history
            history.append({"role": "model", "text": answer})
            
            # Save updated history
            save_chat_history(session_id, url, history)
            
            return {
                'statusCode': 200,
                'headers': headers,
                'body': json.dumps({
                    'success': True,
                    'answer': answer,
                    'session_id': session_id
                })
            }
            
        except Exception as e:
            print(f"Error generating response: {str(e)}")
            # Remove the user message if LLM call failed
            if history and history[-1]["role"] == "user":
                history.pop()
            
            return {
                'statusCode': 500,
                'headers': headers,
                'body': json.dumps({'error': f'Error generating response: {str(e)}'})
            }
        
    except Exception as e:
        print(f"Unhandled error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({'error': f'Internal server error: {str(e)}'})
        }