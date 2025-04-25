import os
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)

class DeepgramTranscriber:
    def __init__(self, bot):
        self.bot = bot  # The bot instance to send transcriptions to Zoom chat

        # Initialize Deepgram API client with KeepAlive option
        config = DeepgramClientOptions(
            options={"keepalive": "true"}
        )

        # Create a WebSocket connection to Deepgram for live transcription
        self.deepgram = DeepgramClient(os.environ.get('DEEPGRAM_API_KEY'), config)
        self.dg_connection = self.deepgram.listen.websocket.v("1")

        # Define the on_message callback function to handle transcriptions
        def on_message(self, result, **kwargs):
            sentence = result.channel.alternatives[0].transcript
            if len(sentence) == 0:
                return
            print(f"Transcription: {sentence}")

            # Send the transcription to the Zoom chat (to you or other participants)
            self.bot.send_transcription_to_chat(sentence)

        # Bind the callback function to the transcription event
        self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)

        # Define the on_error callback function to handle errors
        def on_error(self, error, **kwargs):
            print(f"Error: {error}")

        # Bind the on_error callback to the error event
        self.dg_connection.on(LiveTranscriptionEvents.Error, on_error)

        # Set transcription options (model, language, etc.)
        options = LiveOptions(
            model="nova-2-conversationalai",
            punctuate=True,
            interim_results=True,
            language='en-GB',
            encoding="linear16",
            sample_rate=32000
        )

        # Start the connection for live transcription
        self.dg_connection.start(options)

    def send(self, data):
        self.dg_connection.send(data)

    def finish(self):
        self.dg_connection.finish()

    PCM_FILE_PATH = 'sample_program/out/test_audio_16778240.pcm'
    CHUNK_SIZE = 64000 * 10

    async def send_pcm(self):
        with open(self.PCM_FILE_PATH, 'rb') as pcm_file:
            while True:
                chunk = pcm_file.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                self.send(chunk)
                await asyncio.sleep(0.1)

    def get_pcm_chunk(self):
        with open(self.PCM_FILE_PATH, 'rb') as pcm_file:
            while True:
                chunk = pcm_file.read(self.CHUNK_SIZE)
                return chunk
