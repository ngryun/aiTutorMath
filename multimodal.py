from common import model, client
import base64
import requests
import json

def ask_image(image_file, str):
    user_message = str
    prompt = f"당신은 이미지 속 수학 문제를 OCR 하는 도구입니다. 이미지속 문제의 text와 수식(Latex)만 변환하여 제시하고, 다른 의견은 절대 말하지 마세요. 혹시 문제를 text만으로 표현하기 어려 운경우 그림 속 문제를 설명하고 풀이를 제시합니다"
    encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
    return ask_gpt_vision(prompt, encoded_image)

def ask_gpt_vision(prompt, encoded_image):        
    context = [{
        "role": "user",
        "content": [
            {"type": "text",
            "text": prompt},
            {"type": "image_url","image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}}
        ]}
    ]
    response = client.chat.completions.create(
        model=model.basic,
        messages=context,
        max_tokens=300,
    )    
    return response.model_dump()

def generate_speech(user_message):
    try:
        response = client.audio.speech.create(
            model="tts-1",
            voice="nova", #alloy, echo, fable, onyx, nova, shimmer 중 택1
            input=user_message,
        )
        return response.content
    except Exception as e:
        print(f"Exception 오류({type(e)}) 발생:{e}")
        return ""
    
    