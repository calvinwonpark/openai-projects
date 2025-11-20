# 🎓 TeachMe Live

A real-time voice tutoring application powered by OpenAI's Realtime API. Upload textbook questions or images, and have natural voice conversations with an AI tutor in English or Korean.

## ✨ Features

- **Real-time Voice Conversations**: Natural, bidirectional voice conversations with AI tutor
- **Multilingual Support**: Choose between English or Korean (한국어, 존댓말) responses
- **🆕 Real-Time Translation Mode**: Speak in either Korean or English, AI detects your language and responds in your selected target language with intelligent interpretation
- **🆕 AI Tutor Notes**: Automatically generated study notes summarizing key concepts, examples, common mistakes, and review topics from your session
- **Image Upload**: Upload textbook questions or images and ask questions about them
- **Smart Speech Detection**: Debounced speech stop detection (2-second delay) to avoid cutting off mid-sentence
- **Natural Backchannels**: AI uses natural thinking sounds ("mm-hmm", "let me think", "음...", "그렇군요") while processing
- **Modern UI**: Beautiful, responsive interface with drag-and-drop image upload
- **Live Logging**: Real-time session activity logs for debugging and monitoring

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- OpenAI API key with access to the Realtime API
- Modern web browser with WebRTC support (Chrome, Firefox, Safari, Edge)

### Installation

1. **Clone the repository** (or navigate to the project directory)

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**:
   Create a `.env` file in the project root:
   ```env
   OPENAI_API_KEY=your_openai_api_key_here
   ```

4. **Run the application**:
   ```bash
   uvicorn app:app --reload
   ```

5. **Open your browser**:
   Navigate to `http://localhost:8000`

## 📖 Usage

1. **Choose Language**: Select whether you want responses in English or Korean
2. **🆕 Enable Translator Mode (Optional)**: Toggle "Translator Mode" to allow speaking in either language
   - **OFF (Normal Mode)**: You can ask in any language, AI responds in selected target language
   - **ON (Translator Mode)**: You can speak Korean or English, AI detects your language, interprets, and responds in target language
3. **Upload Image (Optional)**: Drag and drop or click to upload a textbook question image
4. **Start Session**: Click "Start Session" and allow microphone access when prompted
5. **Start Talking**: Once connected, just speak naturally. The AI will:
   - Respond with voice in your selected language
   - Use natural backchannels while thinking ("mm-hmm", "let me think", "음...", "그렇군요")
   - Detect your language automatically (in Translator Mode)
   - Interpret and translate when needed (in Translator Mode)
   - Answer questions about uploaded images

6. **🆕 Generate Tutor Notes**: Click "Update Notes" anytime during or after your session to generate AI-powered study notes:
   - **Key Concepts**: Summary of what you learned
   - **Examples**: Important examples from the conversation
   - **Common Mistakes**: Mistakes to watch out for
   - **Review Topics**: Suggested topics for review
   - Notes are generated in your selected language (English or Korean)
   - Notes stream in real-time as they're generated

### Example Questions

**Normal Mode:**
- "Can you explain the question in the image I uploaded?"
- "What does this problem ask me to do?"
- "How do I solve this step by step?"

**Translator Mode Examples:**

*With Answer Language: English, User speaks Korean:*
- "이 수학 문제를 어떻게 풀어야 해요?" → AI interprets and responds in English

*With Answer Language: Korean, User speaks English:*
- "What does this physics problem want me to do?" → AI interprets and responds in Korean

*Mixed Language (Translator Mode):*
- Start in Korean, switch to English mid-conversation → AI adapts automatically

## 🏗️ Project Structure

```
teachme-live/
├── app.py                 # FastAPI backend server
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables (create this)
├── static/
│   ├── index.html        # Main UI
│   └── realtime.js       # Client-side WebRTC logic
├── uploads/               # Temporary audio files (auto-created)
└── README.md             # This file
```

## 🛠️ Technology Stack

- **Backend**: FastAPI (Python)
- **Frontend**: Vanilla JavaScript, HTML5, CSS3
- **Real-time Communication**: WebRTC, OpenAI Realtime API
- **AI Model**: GPT Realtime (gpt-realtime)
- **Audio**: Web Audio API, MediaStream API
- **Multi-Agent Orchestration**: Realtime API + Responses API (for Tutor Notes)

## 📡 API Endpoints

### `GET /`
Serves the main HTML page.

### `POST /realtime-token`
Generates an ephemeral client secret for connecting to OpenAI's Realtime API.

**Response**:
```json
{
  "client_secret": "ephemeral_key_here"
}
```

## ⚙️ Configuration

### Speech Stop Delay

The application includes a debounced speech stop detection to avoid cutting off users mid-sentence. By default, it waits 2 seconds of silence before detecting speech stop.

To adjust this delay, edit `static/realtime.js`:

```javascript
const SPEECH_STOP_DELAY_MS = 2000; // Change this value (in milliseconds)
```

### Language Instructions

The tutor's behavior can be customized by modifying the instructions in `static/realtime.js`:

- `buildInstructions()` function (line ~55) - Handles both Normal and Translator modes
- English tutor instructions (Normal Mode)
- Korean tutor instructions (Normal Mode)
- Bilingual interpreter instructions (Translator Mode)

The instructions automatically adapt based on:
- Selected target language (English/Korean)
- Translator Mode toggle state (ON/OFF)

## 🐳 Docker Support

The project includes Docker configuration files:

```bash
# Build and run with Docker Compose
docker-compose up --build
```

## 🔧 Troubleshooting

### Microphone Not Working
- Ensure you've granted microphone permissions in your browser
- Check browser console for WebRTC errors
- Try a different browser if issues persist

### Connection Issues
- Verify your OpenAI API key is correct and has Realtime API access
- Check that your internet connection is stable
- Review the browser console logs for detailed error messages

### Image Upload Not Working
- Ensure the image is in a supported format (PNG, JPG, GIF)
- Check that the file size is under 10MB
- Try a different image if issues persist

### Speech Detection Too Sensitive
- Adjust `SPEECH_STOP_DELAY_MS` in `realtime.js` to increase the delay
- Higher values = longer silence required before speech stop detection

### Translator Mode Not Working
- Ensure Translator Mode toggle is checked
- Check that the session is active (data channel must be open)
- Verify language detection is working by checking session logs
- Try toggling Translator Mode off and on again to refresh instructions

### Tutor Notes Not Generating
- Ensure the session is active and connected (data channel must be open)
- Check that you've had some conversation before requesting notes
- Verify the notes panel is visible in the UI
- Check browser console for any error messages
- Try clicking "Update Notes" again if the first attempt fails

## 📝 Development

### Running in Development Mode

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

The `--reload` flag enables auto-reload on code changes.

### Testing

1. Start the server
2. Open the application in your browser
3. Check the browser console (F12) for logs
4. Monitor the session logs in the UI

## 🔒 Security Notes

- The ephemeral client secret is generated server-side and never exposed in the frontend code
- API keys should never be committed to version control
- For production, consider:
  - Restricting CORS origins
  - Adding authentication
  - Using HTTPS
  - Rate limiting

## 📄 License

This project is provided as-is for educational purposes.

## 🤝 Contributing

Feel free to submit issues, fork the repository, and create pull requests for any improvements.

## 🌟 Key Features Explained

### AI Tutor Notes

The Tutor Notes feature demonstrates advanced multi-agent orchestration by combining the Realtime API with the Responses API. It automatically generates comprehensive study notes based on your entire conversation history.

**How It Works:**
1. During or after your session, click the "Update Notes" button
2. The app sends a `response.create` event with text-only modality (no audio)
3. The AI analyzes the conversation history and generates structured notes
4. Notes stream in real-time into the dedicated notes panel
5. Notes are separate from the main chat log for easy reference

**What's Included:**
- **Key Concepts** (핵심 개념): Main topics covered in the session
- **Examples** (예시): Important examples and demonstrations
- **Common Mistakes** (자주 하는 실수): Errors to avoid
- **Review Topics** (복습하면 좋은 포인트): Suggested areas for further study

**Language Support:**
- Notes are generated in your selected target language
- Korean notes use polite form (존댓말)
- English notes use clear, concise academic style

**Technical Highlights:**
- Uses `response.create` to trigger additional AI responses within the Realtime session
- Demonstrates multi-agent orchestration (Realtime + Responses API)
- Text-only modality ensures notes don't interfere with voice conversation
- Metadata tagging allows separate routing of notes vs. normal responses
- Real-time streaming for immediate feedback

**Use Cases:**
- Study session summaries
- Homework review notes
- Vocabulary lists
- Correction logs
- Step-by-step explanation notes
- Homework suggestions

### Real-Time Translation Mode

Translator Mode enables true bilingual conversations:

- **Language Detection**: AI automatically detects whether you're speaking Korean or English
- **Intelligent Interpretation**: When you speak in a different language than the target, AI interprets your intent before responding
- **Context Preservation**: Maintains conversation context across language switches
- **Adaptive Backchannels**: Uses backchannels in the language you're currently speaking
- **Seamless Switching**: You can switch languages mid-conversation and AI adapts automatically

**Use Cases:**
- Korean speakers learning English (speak Korean, get English explanations)
- English speakers learning Korean (speak English, get Korean explanations)
- Mixed-language tutoring sessions
- Cross-lingual homework help

### Natural Backchannels

The AI uses natural thinking sounds to make conversations feel more human:
- **English**: "mm-hmm", "let me think", "okay", "hmm"
- **Korean**: "음...", "그렇군요", "잠시만요", "아..."

These appear when the AI is:
- Analyzing uploaded images
- Working through complex problems
- Formulating explanations
- Processing multi-step calculations

## 🙏 Acknowledgments

- Built with OpenAI's Realtime API
- Uses FastAPI for the backend
- Modern UI design with CSS gradients and animations
- Real-time translation powered by GPT Realtime's multilingual capabilities
- Tutor Notes feature demonstrates multi-agent orchestration with Realtime + Responses API

---

**Note**: This application requires an OpenAI API key with access to the Realtime API. Make sure your API key has the necessary permissions.

