# Setup instructions.

1. Create a bucket for storing the cache and downloaded research paper with a preferred name (e.g. chat-cache-rraghu214-14092025)
    - set a lifecycle for objects to expire by 1 hours. This is to optimize the storage
2. Create gemini key in AWS Secrets Manager
3. Create Layers
    Create Layer-1
    
    Step-A
    ```
    python3 -m pip download \
      --only-binary=:all: \
      --platform manylinux2014_x86_64 \
      --implementation cp \
      --python-version 312 \
      -d wheels1 \
      "boto3" "requests" "beautifulsoup4"
      ```

      ![layer-1-pip-download](z_extras\layer-1-download.png)

    Step-B
    Verify if the wheels are downloaded.
    ![layer-1-pip-download-verification](z_extras\layer-1-pip-download-verification.png)

    Step-C
    ```
     mkdir -p genai-layer1/python
     for f in wheels1/*.whl; do
       unzip -o "$f" -d genai-layer1/python > /dev/null
     done
     ```

    Step-D
    ```
     zip -r genai-layer1.zip python
     genai-layer1 $ aws lambda publish-layer-version \
     >   --layer-name research-paper-layer-1-py312 \
     >   --region ap-south-1 \
     >   --description "Google GenAI SDK layer2 (cp312, manylinux2014_x86_64)" \
     >   --zip-file fileb://genai-layer1.zip \
     >   --compatible-runtimes python3.12
     ```

    ![layer-1-publish](z_extras\layer-1-publish.png)

    Similarly create layer-2, 3 for  "google-genai" "pdfminer.six" "google-auth" 


4. Lambda function for research-paper-summarizer
    - create a new function
    - attach layers
    - attach policies
    - create function URL
    - enable CORS
        - Expose headers (access-control-allow-origin, access-control-allow-headers, access-control-allow-methods, access-control-max-age, content-type)
        - Allow headers (access-control-allow-origin, access-control-allow-headers, access-control-allow-methods, access-control-max-age, content-type)
        - Allow origin *
        - Allow methods *
        - Max age 86400

        ![CORS-Expose-Headers](z_extras\CORS-Expose-Headers.png)

5. Lambda function for chat_with_paper
6. Create bucket for hosting the front end.
    - Go to AWS, create a bucket with a prefered name. (e.g. research-paper-summarizer-rraghu214-13092025)
    - Upload all the files from frontend folder - index.html, main.css, main.js
    - Enable static hosting

    ![Static-Hosting](z_extras\Static-Hosting.png)


    ![Static-Hosting-Created](z_extras\Static-Hosting-Created.png)
    

    - Enable bucket policy

    ![Create-Bucket-Policy](z_extras\Create-Bucket-Policy.png)

    ![Created-Bucket-Policy](z_extras\Created-Bucket-Policy.png)

    ![Created-Bucket-Policy-2](z_extras\Created-Bucket-Policy-2.png)


 7. Create a bucket for caching or storing downloaded research papers or chat conv history. (Optional or reuse the above bucket)

8. Test & verify
    - Test the Lambda endpoint

    ```    

    curl -X OPTIONS \
    >   -H "Origin: https://research-paper-summarizer-rraghu214-13092025.s3.ap-south-1.amazonaws.com" \
    >   -H "Access-Control-Request-Method: POST" \
    >   -H "Access-Control-Request-Headers: Content-Type" \
    >   -i \
    >   https://hx7rwzhjd3xlxqsrzmmxfgx33u0hcdxr.lambda-url.ap-south-1.on.aws/
    ```

    - Test from the UI.

    ![Main-UI](z_extras\MAIN-UI.png)

    Ref: https://claude.ai/chat/0b159b91-2eb5-44b9-965a-c0142ebc5d08