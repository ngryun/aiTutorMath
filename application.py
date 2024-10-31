from flask import Flask, render_template, request, Response, session
from dotenv import load_dotenv
import os
from common import model
from chatbot import Chatbot
import multimodal
import atexit
from pymongo import MongoClient
from uuid import uuid4  # 사용자 고유 ID 생성을 위한 라이브러리
from flask_session import Session

load_dotenv()
# Flask 애플리케이션 생성
application = Flask(__name__)
application.secret_key = os.getenv("SECRET_KEY") # 세션 암호화를 위한 키 설정

application.config['SESSION_TYPE'] = 'filesystem'  # 또는 'redis', 'mongodb' 등
Session(application)
# MongoDB 설정
cluster = MongoClient(os.getenv("uri"))
db = cluster["yeon"]
mongo_chats_collection = db["math"]
user_sessions_collection = db["user_sessions"]  # 사용자별 세션 정보를 저장할 컬렉션

# 사용자별 고유 Chatbot 인스턴스 할당 함수
def get_chatbot_instance():
    user_id = session.get("user_id")
    if not user_id:
        # 만약 세션에 user_id가 없다면 새로 생성하여 저장
        user_id = str(uuid4())
        session["user_id"] = user_id  # 세션에 새로운 사용자 ID 저장
    
    # MongoDB에서 user_id로 Chatbot의 thread_id 상태 확인
    session_data = user_sessions_collection.find_one({"user_id": user_id})
    if not session_data:
        # 사용자에 대한 thread_id가 없으면 새로운 Chatbot 인스턴스를 생성
        chatbot_instance = Chatbot(assistant_id=os.getenv("ASSISTANT_ID"))
        # 새로운 user_id와 thread_id를 MongoDB에 저장
        user_sessions_collection.insert_one({"user_id": user_id, "thread_id": chatbot_instance.thread.id})
    else:
        # 기존 user_id의 thread_id가 있으면 이를 사용하여 Chatbot 인스턴스 생성
        chatbot_instance = Chatbot(assistant_id=os.getenv("ASSISTANT_ID"), user_id=session_data["thread_id"])
        # 현재 thread_id가 DB의 thread_id와 다르면 MongoDB 업데이트
        if chatbot_instance.thread.id != session_data["thread_id"]:
            user_sessions_collection.update_one(
                {"user_id": user_id},
                {"$set": {"thread_id": chatbot_instance.thread.id}},
                upsert=True  # 문서가 없을 경우 새로 생성
            )
    return chatbot_instance

@application.route("/")
def hello():
    return "제작 : 설악고등학교 교사 남궁연" 

@application.route("/checking-app")
def checking_app():
    user_id = request.args.get("user_id")  # 쿼리 파라미터로 user_id를 받음
    if not user_id:
        return "User ID가 제공되지 않았습니다.", 400
    user_chats = mongo_chats_collection.find({"Userid": user_id}).sort("date", 1)  # 특정 user_id와 일치하는 대화만 가져오기
    # HTML 템플릿으로 대화 목록 전달
    return render_template("checking.html", chats=user_chats)

@application.route("/chat-app")
def chat_app():
    # 클라이언트에서 user_id를 요청 파라미터로 받습니다.
    user_id = request.args.get("user_id")  # 쿼리 파라미터로 user_id를 확인
    if user_id:
        # user_sessions_collection에서 user_id 존재 여부 확인
        session_data = user_sessions_collection.find_one({"user_id": user_id})
        if session_data:
            session["user_id"] = user_id  # 세션에 user_id를 저장하여 대화를 시작할 수 있도록 설정
        else:
            return "유효하지 않은 사용자 ID입니다. 접근이 거부되었습니다. 문의: 설악고등학교 교사 남궁연", 403  # 사용자 ID가 없을 경우 접근 거부 응답
    else:
        return "User ID가 제공되지 않았습니다. 문의: 설악고등학교 교사 남궁연", 400  # user_id가 제공되지 않은 경우의 에러 처리

    default_message = """안녕?😊
    나는 중고등학생의 수학 공부 친구 강원아 라고 해.
    현재는 강원도 지역의 특별한 몇 학생들하고만 이야기하고 있어.

    수학 질문하는 방법:
    1) 문제를 글로 설명해줘도 괜찮고~
    2) 사진으로 찍어서 올려도 돼🎈

    아래와 같은 요청도 좋아:
    1) 고등학교 1학년 수학교과서에는 어떤 단원이 있어?
    2) 중학교 2학년 경우의수 단원에서 문제 내줄래?
    3) 집합이란 뭘까?

    좋은 질문과 답변에는 포인트를 줄거야!
    내 실수를 발견하면 반드시 알려줘, 포인트를 듬뿍줄게.
    이런 과정이 더 깊은 수학 학습으로 이어질거야.

    모든 대화 내용은 학교 담당선생님께서 검토하시며 피드백 해주실 수 있어.
    그러니 사적인 대화는 이곳에 적으면 안돼!
    오늘도 즐겁게 수학을 공부하자.
    """
    return render_template("chat.html", default_message=default_message)

@application.route("/audio")
def audio_route():
    user_message = request.args.get("message", "")
    # TTS 요청
    speech = multimodal.generate_speech(user_message)
    return Response(speech, mimetype="audio/mpeg")

@application.route("/chat-api", methods=["POST"])
def chat_api():
    chatbot_instance = get_chatbot_instance()  # 사용자 고유 Chatbot 인스턴스 가져오기
    print(session.get("user_id"))
    try:
        # 요청에서 메시지를 받음
        request_message = request.form.get("message")
        # 이미지 파일이 있는 경우 이미지 분석 요청
        image_file = request.files.get("image")
        if image_file is not None:
            chatbot_instance.add_user_message_image(image_file)
            request_message = request_message + "[사진 업로드]"
        else:
            # print("request_message:", request_message)
            chatbot_instance.add_user_message(request_message)  # 사용자의 메시지 추가

        # Chatbot 인스턴스를 통해 대화 실행
        run = chatbot_instance.create_run()
        _, response_message = chatbot_instance.get_response_content(run)
        response_python_code = chatbot_instance.get_interpreted_code(run.id)

        if "with open" in response_python_code:  # 파일 검색을 위한 코드가 포함된 경우 제외
            response_python_code = None

    except Exception as e:
        print("assistants ai error", e)
        response_message = "[Assistants API 오류가 발생했습니다]"
        return {"response_message": response_message, "response_python_code": None}

    # MongoDB에 대화 내용을 저장
    user_id = session.get("user_id")
    chatbot_instance.memoryManager.save_message("user", request_message, user_id)
    chatbot_instance.memoryManager.save_message("assistant", response_message, user_id)
    print("response_message:", response_message)
    
    return {"response_message": response_message, "response_python_code": response_python_code}

@atexit.register
def shutdown():
    print("Flask shutting down...")
    # 필요시 추가 정리 코드 작성...

if __name__ == "__main__":
    application.config["TEMPLATES_AUTO_RELOAD"] = True
    application.jinja_env.auto_reload = True
    application.run(host="0.0.0.0", port=5000)
