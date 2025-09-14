import json
import os
import hashlib
import boto3
import time
from typing import Dict, Any
from botocore.exceptions import ClientError
from google import genai  # provided by the layer

# Import shared modules
from extractors import extract_text_from_url
from llm import summarize_map_reduce

# AWS Configuration
SECRET_NAME = os.environ.get("GEMINI_SECRET_NAME", "prod/gemini/api_key")
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-2.5-flash")
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
S3_BUCKET = os.environ.get("CACHE_BUCKET_NAME", "chat-cache-rraghu214-14092025")

# S3 Configuration
CACHE_PREFIX = "paper_cache/"
VALID_LEVELS = {"LOW", "MEDIUM", "HIGH"}

# Global caches
_API_KEY_CACHE = None
_CLIENT_CACHE = None

# Initialize AWS clients
s3_client = boto3.client('s3')


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


def cache_paper_s3(url: str, text: str, summaries: Dict[str, str]) -> None:
    """Cache paper data in S3"""
    cache_key = hashlib.md5(url.encode()).hexdigest()
    s3_key = f"{CACHE_PREFIX}{cache_key}.json"
    
    cache_data = {
        "text": text,
        "summaries": summaries,
        "url": url,
        "timestamp": int(time.time())
    }
    
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(cache_data, ensure_ascii=False),
            ContentType='application/json',
            ServerSideEncryption='AES256'  # Optional: encrypt at rest
        )
        print(f"Cached paper data to S3: {s3_key}")
    except Exception as e:
        print(f"Error caching to S3: {str(e)}")
        # Don't raise - caching failure shouldn't break the main functionality


def get_cached_paper_s3(url: str) -> Dict[str, Any] | None:
    """Retrieve cached paper data from S3"""
    cache_key = hashlib.md5(url.encode()).hexdigest()
    s3_key = f"{CACHE_PREFIX}{cache_key}.json"
    
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
        cached_data = json.loads(response['Body'].read().decode('utf-8'))
        print(f"Retrieved cached paper data from S3: {s3_key}")
        return cached_data
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            print(f"No cached data found for: {s3_key}")
            return None
        print(f"Error retrieving from S3: {str(e)}")
        return None
    except Exception as e:
        print(f"Error parsing cached data: {str(e)}")
        return None


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda handler for paper summarization"""
    
    # Set up CORS headers - MUST be consistent across all responses
    headers = {
        # 'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
        'Access-Control-Allow-Methods': 'POST, OPTIONS, GET',
        'Access-Control-Max-Age': '86400',  # Cache preflight for 24 hours
        'Content-Type': 'application/json' # nothing
    }
    
    # Handle OPTIONS request for CORS preflight - CRITICAL: Must return 200
    if event.get('httpMethod') == 'OPTIONS':
        print("Handling CORS preflight request")
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({'message': 'CORS preflight successful'})
        }
    
    # Log the incoming event for debugging
    print(f"Received event: {json.dumps(event, default=str)}")
    
    try:
        # Parse request body with better error handling
        body = None
        if 'body' in event and event['body']:
            if isinstance(event['body'], str):
                try:
                    body = json.loads(event['body'])
                except json.JSONDecodeError as e:
                    print(f"JSON decode error: {str(e)}")
                    return {
                        'statusCode': 400,
                        'headers': headers,
                        'body': json.dumps({'error': 'Invalid JSON in request body'})
                    }
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
        level = body.get('complexity', 'LOW').strip().upper()
        session_id = body.get('session_id', '')
        
        # Validate inputs
        if not url:
            return {
                'statusCode': 400,
                'headers': headers,
                'body': json.dumps({'error': 'Missing paper_url'})
            }
        
        if level not in VALID_LEVELS:
            level = "LOW"
        
        if not (url.startswith("http://") or url.startswith("https://")):
            return {
                'statusCode': 400,
                'headers': headers,
                'body': json.dumps({'error': 'Please enter a valid http(s) URL'})
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
        
        # Check S3 cache first
        cached_data = get_cached_paper_s3(url)
        
        if cached_data is None:
            # Extract text from URL
            try:
                text = extract_text_from_url(url)
                if not text or len(text.strip()) < 200:
                    return {
                        'statusCode': 400,
                        'headers': headers,
                        'body': json.dumps({'error': 'Could not extract enough text from the provided URL'})
                    }
                
                # Initialize cache entry
                cached_data = {"text": text, "summaries": {}}
                cache_paper_s3(url, text, {})
                
            except Exception as e:
                print(f"Error extracting text: {str(e)}")
                return {
                    'statusCode': 500,
                    'headers': headers,
                    'body': json.dumps({'error': f'Error extracting text: {str(e)}'})
                }
        
        # Generate summary if not cached
        if level not in cached_data["summaries"]:
            try:
                summary = summarize_map_reduce(cached_data["text"], level=level)
                cached_data["summaries"][level] = summary
                
                # Update S3 cache
                cache_paper_s3(url, cached_data["text"], cached_data["summaries"])
                
            except Exception as e:
                print(f"Error generating summary: {str(e)}")
                return {
                    'statusCode': 500,
                    'headers': headers,
                    'body': json.dumps({'error': f'Error generating summary: {str(e)}'})
                }
        
        # Return successful response
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({
                'success': True,
                'paper_url': url,
                'level': level,
                'summary': cached_data["summaries"][level],
                'session_id': session_id
            })
        }
        
    except Exception as e:
        print(f"Unhandled error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({'error': f'Internal server error: {str(e)}'})
        }