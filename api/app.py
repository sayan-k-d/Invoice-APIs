from flask import Flask, request, jsonify
from flask_cors import CORS
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import fitz  # PyMuPDF for PDFs
from PIL import Image
import pytesseract
from io import BytesIO
from azure.storage.blob import BlobServiceClient
import os
import openai

app = Flask(__name__)
CORS(app)  # Handle CORS

# Configure your Gmail credentials

GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_PASSWORD = os.environ.get('GMAIL_PASSWORD')

# Azure Blob Storage Configuration
AZURE_CONNECTION_STRING = os.environ.get('AZURE_CONNECTION_STRING')
AZURE_CONTAINER_NAME = os.environ.get('AZURE_CONTAINER_NAME')
blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)

AZURE_OPENAI_KEY=os.environ.get("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT=os.environ.get('AZURE_OPENAI_ENDPOINT')
AZURE_OPENAI_API_TYPE =os.environ.get('AZURE_OPENAI_API_TYPE')
AZURE_OPENAI_API_VERSION=os.environ.get('AZURE_OPENAI_API_VERSION')
AZURE_OPENAI_DEPLOYMENT=os.environ.get('AZURE_OPENAI_DEPLOYMENT')
AZURE_FORM_RECOGNIZER_ENDPOINT=os.environ.get('AZURE_FORM_RECOGNIZER_ENDPOINT')
AZURE_FORM_RECOGNIZER_KEY=os.environ.get('AZURE_FORM_RECOGNIZER_KEY')
AZURE_BLOB_CONNECTION_STRING=os.environ.get('AZURE_BLOB_CONNECTION_STRING')
AZURE_CONTAINER_NAME_SOURCE=os.environ.get('AZURE_CONTAINER_NAME_SOURCE')
AZURE_CONTAINER_TARGET_NAME=os.environ.get('AZURE_CONTAINER_TARGET_NAME')
AZURE_TRANSALATION_SERVICE_ENDPOINT=os.environ.get('AZURE_TRANSALATION_SERVICE_ENDPOINT')
AZURE_TRANSALATION_SERVICE_KEY=os.environ.get('AZURE_TRANSALATION_SERVICE_KEY')
AZURE_SOURCE_CONTAINER_URL=os.environ.get('AZURE_SOURCE_CONTAINER_URL')
AZURE_TARGET_CONTAINER_URL=os.environ.get('AZURE_TARGET_CONTAINER_URL')

CSV_HEADERS = [
    "PL NO", "INV NO", "HSCODE", "Date", "Address", 
    "Tax No", "Commodity", "QTY", "Unit", "Unit Price", 
    "Total Amount", "G.W(KG)", "N.W(KG)"
]

def convert_to_csv(data):
    # Split the data by pipe separator
    rows = data.strip().split('|')
    csv_output = []

    # Add headers to the output
    csv_output.append(','.join(CSV_HEADERS))
      # Ensure no leading/trailing spaces
    csv_output.append(','.join(rows))

    return '\n'.join(csv_output)


def getopenairesponse(all_chunks) :
    content=""
    try:
        # Set your Azure Cognitive Services API key and endpoint
        openai.api_type = AZURE_OPENAI_API_TYPE
        openai.api_version = AZURE_OPENAI_API_VERSION
        openai.api_base = AZURE_OPENAI_ENDPOINT # Your Azure OpenAI resource's endpoint value.
        openai.api_key = AZURE_OPENAI_KEY
        openai_engine=AZURE_OPENAI_DEPLOYMENT
        bot_message=[]
        # Define your conversation context and query
        context_template = f"""
        You are a chatbot for Fluke.com.
        Don't justify your answers. Don't give information not mentioned in the CONTEXT INFORMATION.
        Answer the QUESTION from the CONTEXT below only and follow the INSTRUCTIONS.

        CONTEXT :
        **************
        
        1. Here is the search context {all_chunks}.
        

        QUESTION : PL NO,INV NO,HSCODE,Date,Address,Tax No,Commodity,QTY,Unit,Unit Price,Total Amount,Commodity,G.W(KG),N.W(KG) from the context

        INSTRUCTIONS :
        1. Always provide response only from the CONTEXT.
        2. Provide the response in csv format.
        3. seperate the values using '|' pipe seperator symbol.
        4. Dont provide the columns provide only values
        """
        system_context = {
                        'role': 'system',
                        'content': context_template
                    }
        bot_message.append(system_context)
        # Make a request to the Conversational Agent
        response = openai.ChatCompletion.create(
            engine=openai_engine, # The deployment name you chose when you deployed the GPT-3.5-Turbo or GPT-4 model.
            messages=bot_message,
            frequency_penalty=0,
            n=1,  # Number of messages
            presence_penalty=0,
            temperature=0.0,
            top_p=1,  # Nucleus Sampling
        )
        print(response)
        # To print only the response content text:
        print(response['choices'][0]['message']['content'])
        content=response['choices'][0]['message']['content']
    except Exception as e:
        print(e)
    return content

# Helper function to extract text from a PDF
def extract_text_from_pdf(file_stream):
    text = ""
    pdf_document = fitz.open(stream=file_stream, filetype="pdf")
    for page_num in range(len(pdf_document)):
        page = pdf_document.load_page(page_num)
        text += page.get_text("text")
    return text

# Helper function to extract text from an image
def extract_text_from_image(file_stream):
    image = Image.open(file_stream)
    text = pytesseract.image_to_string(image)
    return text


@app.route('/send-email', methods=['POST'])
def send_email():
    try:
        # Get request data
        data = request.json
        recipient_email = data['to']
        subject = data['subject']
        message_body = data['message']

        # Create the email
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient_email
        msg['Subject'] = subject

        # Attach message body
        msg.attach(MIMEText(message_body, 'plain'))

        # Send the email
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()  # Secure connection
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(GMAIL_USER, recipient_email, text)
        server.quit()

        return jsonify({"status": "success", "message": "Email sent successfully"}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    # Stream file directly to Azure Blob
    blob_client = container_client.get_blob_client(file.filename)
    file_stream = BytesIO(file.read())  # Get file as stream for processing

    blob_client.upload_blob(file_stream, overwrite=True)

    # Reset the stream position for processing
    file_stream.seek(0)

    # Process based on file type
    if file.filename.lower().endswith('.pdf'):
        content = extract_text_from_pdf(file_stream)
        airesponse=getopenairesponse(content)
        values = convert_to_csv(airesponse)
        csvfilename=file.filename.split('.')
        csvfilename=csvfilename[0]
        csv_file_name = f"{csvfilename}.csv"
        blob_client = container_client.get_blob_client(csv_file_name)
        blob_client.upload_blob(values, overwrite=True)
        response = jsonify({"file_type": "PDF", "content": airesponse})
    elif file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
        content = extract_text_from_image(file_stream)
        response = jsonify({"file_type": "Image", "content": content})
    else:
        return jsonify({"error": "Unsupported file type"}), 400

    return response

if __name__ == '__main__':
    app.run()
