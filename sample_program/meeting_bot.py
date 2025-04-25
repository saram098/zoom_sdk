import zoom_meeting_sdk as zoom
import jwt
from deepgram_transcriber import DeepgramTranscriber
from datetime import datetime, timedelta
import os
import cv2
import numpy as np
import gi
gi.require_version('GLib', '2.0')
from gi.repository import GLib


def save_yuv420_frame_as_png(frame_bytes, width, height, output_path):
    try:
        # Convert bytes to numpy array
        yuv_data = np.frombuffer(frame_bytes, dtype=np.uint8)

        # Reshape into I420 format with U/V planes
        yuv_frame = yuv_data.reshape((height * 3 // 2, width))

        # Convert from YUV420 to BGR
        bgr_frame = cv2.cvtColor(yuv_frame, cv2.COLOR_YUV2BGR_I420)

        # Save as PNG
        cv2.imwrite(output_path, bgr_frame)
    except Exception as e:
        print(f"Error saving frame to {output_path}: {e}")


def generate_jwt(client_id, client_secret):
    iat = datetime.utcnow()
    exp = iat + timedelta(hours=24)
    
    payload = {
        "iat": iat,
        "exp": exp,
        "appKey": client_id,
        "tokenExp": int(exp.timestamp())
    }
    
    token = jwt.encode(payload, client_secret, algorithm="HS256")
    return token


def normalized_rms_audio(pcm_data: bytes, sample_width: int = 2) -> bool:
    if len(pcm_data) == 0:
        return True
        
    import array
    samples = array.array('h')  # signed short integer array
    samples.frombytes(pcm_data)
    
    sum_squares = sum(sample * sample for sample in samples)
    rms = (sum_squares / len(samples)) ** 0.5
    
    normalized_rms = rms / 32767.0
    return normalized_rms


def create_red_yuv420_frame(width=640, height=360):
    bgr_frame = np.zeros((height, width, 3), dtype=np.uint8)
    bgr_frame[:, :] = [0, 0, 255]  # Pure red in BGR
    yuv_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2YUV_I420)
    return yuv_frame.tobytes()


class MeetingBot:
    def __init__(self):
        self.deepgram_transcriber = None  # DeepgramTranscriber will be initialized later
        self.chat_ctrl = None
        self.my_participant_id = None
        self.other_participant_id = None
        self.meeting_service = None
        self.setting_service = None
        self.auth_service = None
        self.auth_event = None
        self.recording_event = None
        self.participants_ctrl = None
        self.reminder_controller = None
        self.recording_ctrl = None
        self.audio_ctrl = None
        self.audio_helper = None
        self.audio_settings = None
        self.use_audio_recording = True
        self.use_video_recording = os.environ.get('RECORD_VIDEO') == 'true'
        self.audio_raw_data_sender = None
        self.virtual_audio_mic_event_passthrough = None

    def send_transcription_to_chat(self, transcription):
        builder = self.chat_ctrl.GetChatMessageBuilder()
        builder.SetContent(transcription)
        builder.SetReceiver(self.other_participant_id)  # Send to the other participant
        builder.SetMessageType(zoom.SDKChatMessageType.To_Individual)  # Or .To_All for all participants
        msg = builder.Build()
        send_result = self.chat_ctrl.SendChatMsgTo(msg)
        print(f"send_result = {send_result}")
        builder.Clear()

    def on_join(self):
        self.deepgram_transcriber = DeepgramTranscriber(self)  # Pass 'self' (the bot instance)
        
        self.chat_ctrl = self.meeting_service.GetMeetingChatController()
        self.chat_ctrl_event = zoom.MeetingChatEventCallbacks(onChatMsgNotificationCallback=self.on_chat_msg_notification_callback)
        self.chat_ctrl.SetEvent(self.chat_ctrl_event)
        
        builder = self.chat_ctrl.GetChatMessageBuilder()
        builder.SetContent("Welcome to the Zoom Meeting!")
        builder.SetReceiver(self.my_participant_id)
        builder.SetMessageType(zoom.SDKChatMessageType.To_Individual)
        msg = builder.Build()
        send_result = self.chat_ctrl.SendChatMsgTo(msg)
        print("send_result =", send_result)
        builder.Clear()

    def on_chat_msg_notification_callback(self, chat_msg_info, content):
        print(f"Message ID: {chat_msg_info.GetMessageID()}")
        print(f"Content: {chat_msg_info.GetContent()}")
        # Handle received chat messages if needed

    def cleanup(self):
        if self.meeting_service:
            zoom.DestroyMeetingService(self.meeting_service)
            print("Destroyed Meeting service")
        if self.setting_service:
            zoom.DestroySettingService(self.setting_service)
            print("Destroyed Setting service")
        if self.auth_service:
            zoom.DestroyAuthService(self.auth_service)
            print("Destroyed Auth service")

        if self.audio_helper:
            self.audio_helper.unSubscribe()
            print("audio_helper.unSubscribe()")

        print("CleanUPSDK() called")
        zoom.CleanUPSDK()
        print("CleanUPSDK() finished")

    def init(self):
        if os.environ.get('MEETING_ID') is None:
            raise Exception('No MEETING_ID found in environment.')
        if os.environ.get('MEETING_PWD') is None:
            raise Exception('No MEETING_PWD found in environment.')
        if os.environ.get('ZOOM_APP_CLIENT_ID') is None:
            raise Exception('No ZOOM_APP_CLIENT_ID found in environment.')
        if os.environ.get('ZOOM_APP_CLIENT_SECRET') is None:
            raise Exception('No ZOOM_APP_CLIENT_SECRET found in environment.')

        init_param = zoom.InitParam()
        init_param.strWebDomain = "https://zoom.us"
        init_param.strSupportUrl = "https://zoom.us"
        init_param.enableGenerateDump = True
        init_param.emLanguageID = zoom.SDK_LANGUAGE_ID.LANGUAGE_English
        init_param.enableLogByDefault = True

        init_sdk_result = zoom.InitSDK(init_param)
        if init_sdk_result != zoom.SDKERR_SUCCESS:
            raise Exception('InitSDK failed')

        self.create_services()

    def create_services(self):
        self.meeting_service = zoom.CreateMeetingService()
        self.setting_service = zoom.CreateSettingService()
        self.auth_event = zoom.AuthServiceEventCallbacks(onAuthenticationReturnCallback=self.auth_return)
        self.auth_service = zoom.CreateAuthService()
        self.auth_service.SetEvent(self.auth_event)

        auth_context = zoom.AuthContext()
        auth_context.jwt_token = generate_jwt(os.environ.get('ZOOM_APP_CLIENT_ID'), os.environ.get('ZOOM_APP_CLIENT_SECRET'))

        result = self.auth_service.SDKAuth(auth_context)

        if result != zoom.SDKError.SDKERR_SUCCESS:
            print("Authentication failed with error:", result)

    def auth_return(self, result):
        if result == zoom.AUTHRET_SUCCESS:
            print("Auth completed successfully.")
            self.join_meeting()
        else:
            print("Authentication failed.")

    def join_meeting(self):
        mid = os.environ.get('MEETING_ID')
        password = os.environ.get('MEETING_PWD')
        display_name = "My meeting bot"
        meeting_number = int(mid)

        join_param = zoom.JoinParam()
        join_param.userType = zoom.SDKUserType.SDK_UT_WITHOUT_LOGIN
        param = join_param.param
        param.meetingNumber = meeting_number
        param.userName = display_name
        param.psw = password

        join_result = self.meeting_service.Join(join_param)
        print("join_result =", join_result)

        self.audio_settings = self.setting_service.GetAudioSettings()
        self.audio_settings.EnableAutoJoinAudio(True)

