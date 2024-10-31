from common import client, makeup_response, gpt_num_tokens
import math
from memory_manager import MemoryManager
import openai
import json
from pprint import pprint
import time
import datetime
from retry import retry
from typing import Tuple
import base64

class Chatbot:
    def __init__(self, assistant_id, user_id=None):
        # assistant_id와 user_id를 인자로 받아옴
        self.assistant = client.beta.assistants.retrieve(assistant_id=assistant_id)
        
        # user_id가 없으면 새로 생성하고, 있으면 기존 thread_id를 사용
        if user_id:
            try:
                # 특정 사용자 ID를 기반으로 thread_id를 설정
                self.thread = client.beta.threads.retrieve(thread_id=user_id)
            except Exception as e:
                # thread_id가 없거나 오류가 발생하면 새 스레드 생성
                print(f"Error retrieving thread: {e}, creating new thread.")
                thread = client.beta.threads.create()
                self.thread = client.beta.threads.retrieve(thread_id=thread.id)
        else:
            # 새로운 사용자의 경우 새 thread 생성
            thread = client.beta.threads.create()
            self.thread = client.beta.threads.retrieve(thread_id=thread.id)

        self.runs = list(client.beta.threads.runs.list(thread_id=self.thread.id))
        self.memoryManager = MemoryManager()
        
    @retry(tries=3, delay=2)
    def add_user_message(self, user_message):
        try:
            client.beta.threads.messages.create(
                thread_id=self.thread.id,
                role="user",
                content=user_message,
            )

            
        except openai.BadRequestError as e:
            if len(self.runs) > 0:
                print("add_user_message BadRequestError", e)
                client.beta.threads.runs.cancel(thread_id=self.thread.id, run_id=self.runs[0])
            raise e


    @retry(tries=3, delay=2)
    def add_user_message_image(self,image_file):
        try:
            #encoded_image = base64.b64encode(image_file.read()).decode('utf-8')

            file = client.files.create(
                #file=open('logo.png', "rb"),
                #file=image_file,
                file=(image_file.filename, image_file.stream),
                purpose="vision"
            )

            # 이미지 URL 형식으로 전달 (type을 명시)
            content = [
                {
                "type": "image_file",
                "image_file": {"file_id": file.id}
                }
            ]

            # 이미지 데이터를 API에 전달
            client.beta.threads.messages.create(
                thread_id=self.thread.id,
                role="user",
                content=content  # 이미지 데이터를 포함하여 전달
            )
            
        except openai.BadRequestError as e:
            if len(self.runs) > 0:
                print("add_user_message_image BadRequestError", e)
                client.beta.threads.runs.cancel(thread_id=self.thread.id, run_id=self.runs[0])
            raise e
        

    def _run_action(self, retrieved_run):
        tool_calls = retrieved_run.model_dump()['required_action']['submit_tool_outputs']['tool_calls']
        pprint(("tool_calls", tool_calls))
        tool_outputs=[]
        for tool_call in tool_calls:
            pprint(("tool_call", tool_call))
            id = tool_call["id"]
            function = tool_call["function"]
            func_name = function["name"]
            # 챗GPT가 알려준 함수명에 대응하는 실제 함수를 func_to_call에 담는다.
            func_to_call = self.available_functions[func_name]
            try:
                func_args = json.loads(function["arguments"])
                # 챗GPT가 알려주는 매개변수명과 값을 입력값으로하여 실제 함수를 호출한다.
                print("func_args:",func_args)
                func_response = func_to_call(**func_args)
                tool_outputs.append({
                    "tool_call_id": id,
                    "output": str(func_response)
                })
            except Exception as e:
                    print("_run_action error occurred:",e)
                    client.beta.threads.runs.cancel(thread_id=self.thread.id, run_id=retrieved_run.id)
                    raise e
                    
        client.beta.threads.runs.submit_tool_outputs(
            thread_id = self.thread.id, 
            run_id = retrieved_run.id, 
            tool_outputs= tool_outputs
        )   
    @retry(tries=3, delay=2)    
    def create_run(self):
        try:
            run = client.beta.threads.runs.create(
                thread_id=self.thread.id,
                assistant_id=self.assistant.id,
            )
            self.runs.append(run.id)
            return run
        except openai.BadRequestError as e:
            if len(self.runs) > 0:
                print("create_run BadRequestError", e)
                client.beta.threads.runs.cancel(thread_id=self.thread.id, run_id=self.runs[0])
            raise e        

    def get_response_content(self, run) -> Tuple[openai.types.beta.threads.run.Run, str]:

        max_polling_time = 60 # 최대 1분 동안 폴링합니다.
        start_time = time.time()

        retrieved_run = run
        
        while(True):
            elapsed_time  = time.time() - start_time
            if elapsed_time  > max_polling_time:
                client.beta.threads.runs.cancel(thread_id=self.thread.id, run_id=run.id)
                return retrieved_run, "대기 시간 초과(retrieve)입니다."
            
            retrieved_run = client.beta.threads.runs.retrieve(
                thread_id=self.thread.id,
                run_id=run.id
            )            
            print(f"run status: {retrieved_run.status}, 경과:{elapsed_time: .2f}초")
            
            if retrieved_run.status == "completed":
                break
            elif retrieved_run.status == "requires_action":
                self._run_action(retrieved_run)
            elif retrieved_run.status in ["failed", "cancelled", "expired"]:
                # 실패, 취소, 만료 등 오류 상태 처리
                #raise ValueError(f"run status: {retrieved_run.status}, {retrieved_run.last_error}")
                code = retrieved_run.last_error.code
                message = retrieved_run.last_error.message
                return retrieved_run, f"{code}: {message}"
            
            time.sleep(1) 
            
        # Run이 완료된 후 메시지를 가져옵니다.
        self.messages = client.beta.threads.messages.list(
            thread_id=self.thread.id
        )
        # 오류를 방지하면서 m.content[0]의 값을 출력합니다.
        resp_message = [m.content[0].text for m in self.messages if m.run_id == run.id][0]
        return retrieved_run, resp_message.value
 
    def get_interpreted_code(self, run_id):
        run_steps_dict = client.beta.threads.runs.steps.list(
            thread_id=self.thread.id,
            run_id=run_id
        ).model_dump()
        for run_step_data in run_steps_dict['data']:
            step_details = run_step_data['step_details']
            print("step_details", step_details)
            tool_calls = step_details.get('tool_calls', [])
            for tool_call in tool_calls:
                if tool_call['type'] == 'code_interpreter':
                    return tool_call['code_interpreter']['input']
        return ""
    
    def _send_request(self):
        try:
            context = self.to_openai_contenxt()
            if gpt_num_tokens(context) > self.max_token_size:
                self.context.pop()
                return makeup_response("메시지 조금 짧게 보내줄래?")
            else:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=context,
                    temperature=0.5,
                    top_p=1,
                    max_tokens=256,
                    frequency_penalty=0,
                    presence_penalty=0
                ).model_dump()            
        except Exception as e:
            print(f"Exception 오류({type(e)}) 발생:{e}")
            return makeup_response("[내 찐친 챗봇에 문제가 발생했습니다. 잠시 뒤 이용해주세요]")
        return response
    
    def send_request(self):
        self.context[-1]['content'] += self.instruction
        return self._send_request()        
 
    def add_response(self, response):
        self.context.append({
                "role" : response['choices'][0]['message']["role"],
                "content" : response['choices'][0]['message']["content"],
                "saved" : False
            }
        )
    def clean_context(self):
        for idx in reversed(range(len(self.context))):
            if self.context[idx]["role"] == "user":
                self.context[idx]["content"] = self.context[idx]["content"].split("instruction:\n")[0].strip()
                break
    
    def handle_token_limit(self, response):
        # 누적 토큰 수가 임계점을 넘지 않도록 제어한다.
        try:
            if response['usage']['total_tokens'] > self.max_token_size:
                remove_size = math.ceil(len(self.context) / 10)
                self.context = [self.context[0]] + self.context[remove_size+1:]
        except Exception as e:
            print(f"handle_token_limit exception:{e}")

    def to_openai_contenxt(self):
        return [{"role":v["role"], "content":v["content"]} for v in self.context]
    
    def save_chat(self):
        self.memoryManager.save_chat(self.context)

    def save_chat2(self):
        self.memoryManager.save_chat(self.context)