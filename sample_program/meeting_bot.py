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
        yuv_frame = yuv_data.reshape((height * 3//2, width))

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
    """
    Determine if PCM audio data contains significant audio or is essentially silence.
    
    Args:
        pcm_data: Bytes object containing PCM audio data in linear16 format
        threshold: RMS amplitude threshold below which audio is considered silent (0.0 to 1.0)
        sample_width: Number of bytes per sample (2 for linear16)
        
    Returns:
        bool: True if the audio is essentially silence, False if it contains significant audio
    """
    if len(pcm_data) == 0:
        return True
        
    # Convert bytes to 16-bit integers
    import array
    samples = array.array('h')  # signed short integer array
    samples.frombytes(pcm_data)
    
    # Calculate RMS amplitude
    sum_squares = sum(sample * sample for sample in samples)
    rms = (sum_squares / len(samples)) ** 0.5
    
    # Normalize RMS to 0.0-1.0 range
    # For 16-bit audio, max value is 32767
    normalized_rms = rms / 32767.0
    
    return normalized_rms

def create_red_yuv420_frame(width=640, height=360):
    # Create BGR frame (red is [0,0,255] in BGR)
    bgr_frame = np.zeros((height, width, 3), dtype=np.uint8)
    bgr_frame[:, :] = [0, 0, 255]  # Pure red in BGR
    
    # Convert BGR to YUV420 (I420)
    yuv_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2YUV_I420)
    
    # Return as bytes
    return yuv_frame.tobytes()

class MeetingBot:
    def __init__(self):
        
        self.meeting_service = None
        self.setting_service = None
        self.auth_service = None

        self.auth_event = None
        self.recording_event = None
        self.meeting_service_event = None

        self.audio_source = None
        self.audio_helper = None

        self.audio_settings = None

        self.use_audio_recording = True
        self.use_video_recording = os.environ.get('RECORD_VIDEO') == 'true'

        self.reminder_controller = None

        self.recording_ctrl = None
        self.audio_ctrl = None
        self.audio_ctrl_event = None
        self.audio_raw_data_sender = None
        self.virtual_audio_mic_event_passthrough = None

        self.deepgram_transcriber = DeepgramTranscriber()

        self.my_participant_id = None
        self.other_participant_id = None
        self.participants_ctrl = None
        self.meeting_reminder_event = None
        self.audio_print_counter = 0

        self.video_helper = None
        self.renderer_delegate = None
        self.video_frame_counter = 0

        self.meeting_video_controller = None
        self.video_sender = None
        self.virtual_camera_video_source = None
        self.video_source_helper = None

        self.meeting_sharing_controller = None
        self.meeting_share_ctrl_event = None

        self.chat_ctrl = None
        self.chat_ctrl_event = None

        self.deepgram_transcriber = None  # Will be initialized later
        self.chat_ctrl = None  # Zoom chat controller
        self.my_participant_id = None
        self.other_participant_id = None

    def send_transcription_to_chat(self, transcription):
        # Send the transcription to Zoom chat
        builder = self.chat_ctrl.GetChatMessageBuilder()
        builder.SetContent(transcription)
        builder.SetReceiver(self.other_participant_id)  # Send to the other participant (or to you)
        builder.SetMessageType(zoom.SDKChatMessageType.To_Individual)  # Or .To_All for all participants
        msg = builder.Build()
        send_result = self.chat_ctrl.SendChatMsgTo(msg)
        print(f"send_result = {send_result}")
        builder.Clear()

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
            audio_helper_unsubscribe_result = self.audio_helper.unSubscribe()
            print("audio_helper.unSubscribe() returned", audio_helper_unsubscribe_result)

        if self.video_helper:
            video_helper_unsubscribe_result = self.video_helper.unSubscribe()
            print("video_helper.unSubscribe() returned", video_helper_unsubscribe_result)

        print("CleanUPSDK() called")
        zoom.CleanUPSDK()
        print("CleanUPSDK() finished")

    def init(self):
        if os.environ.get('MEETING_ID') is None:
            raise Exception('No MEETING_ID found in environment. Please define this in a .env file located in the repository root')
        if os.environ.get('MEETING_PWD') is None:
            raise Exception('No MEETING_PWD found in environment. Please define this in a .env file located in the repository root')
        if os.environ.get('ZOOM_APP_CLIENT_ID') is None:
            raise Exception('No ZOOM_APP_CLIENT_ID found in environment. Please define this in a .env file located in the repository root')
        if os.environ.get('ZOOM_APP_CLIENT_SECRET') is None:
            raise Exception('No ZOOM_APP_CLIENT_SECRET found in environment. Please define this in a .env file located in the repository root')

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

    def on_user_join_callback(self, joined_user_ids, user_name):
        print("on_user_join_callback called. joined_user_ids =", joined_user_ids, "user_name =", user_name)

    def on_sharing_status_callback(self, sharing_status):
        print("on_sharing_status_callback called. sharing_status =", sharing_status, "user_id =", sharing_status.userid)

    # NOTE: content will always be None use chat_msg_info.GetContent() instead
    def on_chat_msg_notification_callback(self, chat_msg_info, content):
        print("\n=== on_chat_msg_notification called ===")
        print(f"Message ID: {chat_msg_info.GetMessageID()}")
        print(f"Sender ID: {chat_msg_info.GetSenderUserId()}")
        print(f"Sender Name: {chat_msg_info.GetSenderDisplayName()}")
        print(f"Receiver ID: {chat_msg_info.GetReceiverUserId()}")
        print(f"Receiver Name: {chat_msg_info.GetReceiverDisplayName()}")
        print(f"Content: {chat_msg_info.GetContent()}")
        print(f"Timestamp: {chat_msg_info.GetTimeStamp()}")
        print(f"Message Type: {chat_msg_info.GetChatMessageType()}")
        print(f"Is Chat To All: {chat_msg_info.IsChatToAll()}")
        print(f"Is Chat To All Panelist: {chat_msg_info.IsChatToAllPanelist()}")
        print(f"Is Chat To Waitingroom: {chat_msg_info.IsChatToWaitingroom()}")
        print(f"Is Comment: {chat_msg_info.IsComment()}")
        print(f"Is Thread: {chat_msg_info.IsThread()}")
        print(f"Thread ID: {chat_msg_info.GetThreadID()}")    
        print("=====================\n")

    def on_join(self):

        self.deepgram_transcriber = DeepgramTranscriber(self)

        self.meeting_reminder_event = zoom.MeetingReminderEventCallbacks(onReminderNotifyCallback=self.on_reminder_notify)
        self.reminder_controller = self.meeting_service.GetMeetingReminderController()
        self.reminder_controller.SetEvent(self.meeting_reminder_event)
        

        if self.use_audio_recording:
            self.recording_ctrl = self.meeting_service.GetMeetingRecordingController()

            def on_recording_privilege_changed(can_rec):
                print("on_recording_privilege_changed called. can_record =", can_rec)
                if can_rec:
                    GLib.timeout_add_seconds(1, self.start_raw_recording)
                else:
                    self.stop_raw_recording()

            self.recording_event = zoom.MeetingRecordingCtrlEventCallbacks(onRecordPrivilegeChangedCallback=on_recording_privilege_changed)
            self.recording_ctrl.SetEvent(self.recording_event)

            GLib.timeout_add_seconds(1, self.start_raw_recording)

        self.participants_ctrl = self.meeting_service.GetMeetingParticipantsController()
        self.participants_ctrl_event = zoom.MeetingParticipantsCtrlEventCallbacks(onUserJoinCallback=self.on_user_join_callback)
        self.participants_ctrl.SetEvent(self.participants_ctrl_event)
        self.my_participant_id = self.participants_ctrl.GetMySelfUser().GetUserID()

        participant_ids_list = self.participants_ctrl.GetParticipantsList()
        print("participant_ids_list", participant_ids_list)
        for participant_id in participant_ids_list:
            if participant_id != self.my_participant_id:
                self.other_participant_id = participant_id
                break
        print("other_participant_id", self.other_participant_id)

        self.meeting_sharing_controller = self.meeting_service.GetMeetingShareController()
        self.meeting_share_ctrl_event = zoom.MeetingShareCtrlEventCallbacks(onSharingStatusCallback=self.on_sharing_status_callback)
        self.meeting_sharing_controller.SetEvent(self.meeting_share_ctrl_event)
        viewable_sharing_user_list = self.meeting_sharing_controller.GetViewableSharingUserList()
        print("viewable_sharing_user_list", viewable_sharing_user_list)
        for user_id in viewable_sharing_user_list:
            sharing_info_list_for_user = self.meeting_sharing_controller.GetSharingSourceInfoList(user_id)
            print("sharing_info_list_for_user", user_id, " = ", sharing_info_list_for_user)

        self.audio_ctrl = self.meeting_service.GetMeetingAudioController()
        self.audio_ctrl_event = zoom.MeetingAudioCtrlEventCallbacks(onUserAudioStatusChangeCallback=self.on_user_audio_status_change_callback, onUserActiveAudioChangeCallback=self.on_user_active_audio_change_callback)
        self.audio_ctrl.SetEvent(self.audio_ctrl_event)
        
        self.chat_ctrl = self.meeting_service.GetMeetingChatController()
        self.chat_ctrl_event = zoom.MeetingChatEventCallbacks(onChatMsgNotificationCallback=self.on_chat_msg_notification_callback)
        self.chat_ctrl.SetEvent(self.chat_ctrl_event)

        # Send a welcome message to the chat
        builder = self.chat_ctrl.GetChatMessageBuilder()
        builder.SetContent("Welcoome to the PyZoomMeetingSDK")
        builder.SetReceiver(0)
        builder.SetMessageType(zoom.SDKChatMessageType.To_All)
        msg = builder.Build()
        send_result = self.chat_ctrl.SendChatMsgTo(msg)
        print("send_result =", send_result)
        builder.Clear()

    def on_user_active_audio_change_callback(self, user_ids):
        print("on_user_active_audio_change_callback called. user_ids =", user_ids)

    def on_user_audio_status_change_callback(self, user_audio_statuses, otherstuff):
        print("on_user_audio_status_change_callback called. user_audio_statuses =", user_audio_statuses, "otherstuff =", otherstuff)

    def on_mic_initialize_callback(self, sender):
        print("on_mic_initialize_callback called")
        self.audio_raw_data_sender = sender

    def on_mic_start_send_callback(self):
        print("on_mic_start_send_callback called")
        audio_path = 'sample_program/input_audio/test_audio_16778240.pcm'
        if not os.path.exists(audio_path):
            print(f"Audio file not found: {audio_path}")
            return
            
        with open(audio_path, 'rb') as pcm_file:
            chunk = pcm_file.read(64000*10)
            self.audio_raw_data_sender.send(chunk, 32000, zoom.ZoomSDKAudioChannel_Mono)

    def on_one_way_audio_raw_data_received_callback(self, data, node_id):
        if os.environ.get('DEEPGRAM_API_KEY') is None:
            volume = normalized_rms_audio(data.GetBuffer())
            if self.audio_print_counter % 20 < 2 and volume > 0.01:
                print("Received audio from user", self.participants_ctrl.GetUserByUserID(node_id).GetUserName(), "with volume", volume)
                print("To get transcript add DEEPGRAM_API_KEY to the .env file")
            self.audio_print_counter += 1
            return

        if node_id != self.my_participant_id:
            self.write_to_deepgram(data) 
       
    def write_to_deepgram(self, data):
        try:
            buffer_bytes = data.GetBuffer()
            self.deepgram_transcriber.send(buffer_bytes)
        except IOError as e:
            print(f"Error: failed to open or write to audio file path: {path}. Error: {e}")
            return
        except Exception as e:
            print(f"Unexpected error occurred: {e}")
            return

    def write_to_file(self, path, data):
        try:
            buffer_bytes = data.GetBuffer()          

            with open(path, 'ab') as file:
                file.write(buffer_bytes)
        except IOError as e:
            print(f"Error: failed to open or write to audio file path: {path}. Error: {e}")
            return
        except Exception as e:
            print(f"Unexpected error occurred: {e}")
            return

    def start_raw_recording(self):
        self.recording_ctrl = self.meeting_service.GetMeetingRecordingController()

        can_start_recording_result = self.recording_ctrl.CanStartRawRecording()
        if can_start_recording_result != zoom.SDKERR_SUCCESS:
            self.recording_ctrl.RequestLocalRecordingPrivilege()
            print("Requesting recording privilege.")
            return

        start_raw_recording_result = self.recording_ctrl.StartRawRecording()
        if start_raw_recording_result != zoom.SDKERR_SUCCESS:
            print("Start raw recording failed.")
            return

        self.audio_helper = zoom.GetAudioRawdataHelper()
        if self.audio_helper is None:
            print("audio_helper is None")
            return
        
        if self.audio_source is None:
            self.audio_source = zoom.ZoomSDKAudioRawDataDelegateCallbacks(onOneWayAudioRawDataReceivedCallback=self.on_one_way_audio_raw_data_received_callback, collectPerformanceData=True)

        audio_helper_subscribe_result = self.audio_helper.subscribe(self.audio_source, False)
        print("audio_helper_subscribe_result =",audio_helper_subscribe_result)

        self.virtual_audio_mic_event_passthrough = zoom.ZoomSDKVirtualAudioMicEventCallbacks(onMicInitializeCallback=self.on_mic_initialize_callback,onMicStartSendCallback=self.on_mic_start_send_callback)
        audio_helper_set_external_audio_source_result = self.audio_helper.setExternalAudioSource(self.virtual_audio_mic_event_passthrough)
        print("audio_helper_set_external_audio_source_result =", audio_helper_set_external_audio_source_result)

        self.renderer_delegate = zoom.ZoomSDKRendererDelegateCallbacks(onRawDataFrameReceivedCallback=self.on_raw_data_frame_received_callback)
        self.video_helper = zoom.createRenderer(self.renderer_delegate)

        self.video_helper.setRawDataResolution(zoom.ZoomSDKResolution_720P)
        subscribe_result = self.video_helper.subscribe(self.other_participant_id, zoom.ZoomSDKRawDataType.RAW_DATA_TYPE_VIDEO)
        print("video_helper subscribe_result =", subscribe_result)

        self.virtual_camera_video_source = zoom.ZoomSDKVideoSourceCallbacks(onInitializeCallback=self.on_virtual_camera_initialize_callback, onStartSendCallback=self.on_virtual_camera_start_send_callback)
        self.video_source_helper = zoom.GetRawdataVideoSourceHelper()
        if self.video_source_helper:
            print("video_source_helper is not None")
            set_external_video_source_result = self.video_source_helper.setExternalVideoSource(self.virtual_camera_video_source)
            print("set_external_video_source_result =", set_external_video_source_result)
            if set_external_video_source_result == zoom.SDKERR_SUCCESS:
                print("starting video")
                self.meeting_video_controller = self.meeting_service.GetMeetingVideoController()
                print("meeting_video_controller =", self.meeting_video_controller)
                print("unmuting video")
                self.meeting_video_controller.UnmuteVideo()
                print("unmuted video")
        else:
            print("video_source_helper is None")

    def on_virtual_camera_start_send_callback(self):
        print("on_virtual_camera_start_send_callback called")
        if self.video_sender:
            red_frame = create_red_yuv420_frame(640, 360)
            self.video_sender.sendVideoFrame(red_frame, 640, 360, 0, zoom.FrameDataFormat_I420_FULL)

    def on_virtual_camera_initialize_callback(self, video_sender, support_cap_list, suggest_cap):
        print("on_virtual_camera_initialize_callback called")
        self.video_sender = video_sender

    def on_raw_data_frame_received_callback(self, data):
        if self.video_frame_counter % 10 == 0:
            frame_number = int(self.video_frame_counter / 10)
            save_yuv420_frame_as_png(data.GetBuffer(), 640, 360, f"sample_program/out/video_frames/output_{frame_number:06d}.png")
            print(f"Saved frame {frame_number} to sample_program/out/video_frames/output_{frame_number:06d}.png")
        self.video_frame_counter += 1

    def stop_raw_recording(self):
        rec_ctrl = self.meeting_service.StopRawRecording()
        if rec_ctrl.StopRawRecording() != zoom.SDKERR_SUCCESS:
            raise Exception("Error with stop raw recording")

    def leave(self):
        if self.meeting_service is None:
            return
        
        status = self.meeting_service.GetMeetingStatus()
        if status == zoom.MEETING_STATUS_IDLE:
            return

        self.meeting_service.Leave(zoom.LEAVE_MEETING)


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
        param.vanityID = ""
        param.customer_key = ""
        param.webinarToken = ""
        param.onBehalfToken = ""
        param.isVideoOff = False
        param.isAudioOff = False

        join_result = self.meeting_service.Join(join_param)
        print("join_result =",join_result)

        self.audio_settings = self.setting_service.GetAudioSettings()
        self.audio_settings.EnableAutoJoinAudio(True)

    def on_reminder_notify(self, content, handler):
        if handler:
            handler.accept()

    def auth_return(self, result):
        if result == zoom.AUTHRET_SUCCESS:
            print("Auth completed successfully.")
            return self.join_meeting()

        raise Exception("Failed to authorize. result =", result)
    
    def meeting_status_changed(self, status, iResult):
        if status == zoom.MEETING_STATUS_INMEETING:
            return self.on_join()
        
        print("meeting_status_changed called. status =",status,"iResult=",iResult)

    def create_services(self):
        self.meeting_service = zoom.CreateMeetingService()
        
        self.setting_service = zoom.CreateSettingService()

        self.meeting_service_event = zoom.MeetingServiceEventCallbacks(onMeetingStatusChangedCallback=self.meeting_status_changed)
                
        meeting_service_set_revent_result = self.meeting_service.SetEvent(self.meeting_service_event)
        if meeting_service_set_revent_result != zoom.SDKERR_SUCCESS:
            raise Exception("Meeting Service set event failed")
        
        self.auth_event = zoom.AuthServiceEventCallbacks(onAuthenticationReturnCallback=self.auth_return)

        self.auth_service = zoom.CreateAuthService()

        set_event_result = self.auth_service.SetEvent(self.auth_event)
        print("set_event_result =",set_event_result)
    
        # Use the auth service
        auth_context = zoom.AuthContext()
        auth_context.jwt_token = generate_jwt(os.environ.get('ZOOM_APP_CLIENT_ID'), os.environ.get('ZOOM_APP_CLIENT_SECRET'))

        result = self.auth_service.SDKAuth(auth_context)
    
        if result == zoom.SDKError.SDKERR_SUCCESS:
            print("Authentication successful")
        else:
            print("Authentication failed with error:", result)