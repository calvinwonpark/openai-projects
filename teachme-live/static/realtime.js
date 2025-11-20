// static/realtime.js

const logEl = document.getElementById("log");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const statusEl = document.getElementById("status");
const statusIndicator = document.getElementById("statusIndicator");
const remoteAudio = document.getElementById("remoteAudio");
const imageInput = document.getElementById("imageInput");
const imageStatus = document.getElementById("imageStatus");
const uploadArea = document.getElementById("uploadArea");
const translatorToggle = document.getElementById("translatorToggle");
const notesEl = document.getElementById("tutorNotes");
const updateNotesBtn = document.getElementById("updateNotesBtn");

// Map response_id -> kind ("tutor_notes" vs normal response)
const responseKinds = {};

let pc = null;                  // RTCPeerConnection
let dc = null;                  // RTCDataChannel
let localStream = null;         // mic stream
let clientSecret = null;        // ephemeral key
let uploadedImageUrl = null;    // "data:image/png;base64,..." string
let speechStopTimeout = null;   // Timeout for debouncing speech stop
const SPEECH_STOP_DELAY_MS = 2000; // Wait 2 seconds of silence before detecting speech stop

function log(msg) {
  console.log(msg);
  logEl.textContent += msg + "\n";
  logEl.scrollTop = logEl.scrollHeight;
}

function setStatus(text) {
  statusEl.textContent = "Status: " + text;
  
  // Update status indicator
  if (statusIndicator) {
    statusIndicator.className = "status-indicator";
    const statusLower = text.toLowerCase();
    if (statusLower.includes("connected")) {
      statusIndicator.classList.add("connected");
    } else if (statusLower.includes("connecting") || statusLower.includes("starting")) {
      statusIndicator.classList.add("connecting");
    } else if (statusLower.includes("error") || statusLower.includes("failed")) {
      statusIndicator.classList.add("error");
    }
  }
}

function getTargetLanguage() {
  const checked = document.querySelector('input[name="lang"]:checked');
  return checked ? checked.value : "en";
}

function isTranslatorMode() {
  return translatorToggle && translatorToggle.checked;
}

// ------------------------------
// Tutor Notes Helpers
// ------------------------------
function appendToNotes(text) {
  if (!notesEl) return;
  notesEl.textContent += text;
  notesEl.scrollTop = notesEl.scrollHeight;
}

function clearNotes() {
  if (!notesEl) return;
  notesEl.textContent = "";
}

// Build instructions based on language + translator mode
function buildInstructions(targetLang, translatorMode) {
  if (translatorMode) {
    // TRANSLATOR MODE
    if (targetLang === "ko") {
      return (
        "You are a real-time bilingual interpreter and tutor for Korean and English.\n" +
        "- The user may speak in Korean or English.\n" +
        "- ALWAYS respond in natural, polite Korean (존댓말).\n" +
        "- If the user speaks English, briefly interpret their intent into Korean in your own words, then provide a helpful Korean explanation or answer.\n" +
        "- If the user speaks Korean, focus on clarifying, expanding, and correcting their Korean as needed.\n" +
        "- Use SHORT Korean backchannels like \"음…\", \"그렇군요\", \"잠시만요\" while thinking or listening.\n" +
        "- When the user asks about an uploaded image, first summarize what the question in the image is asking, then explain step-by-step in Korean."
      );
    } else {
      // targetLang === "en"
      return (
        "You are a real-time bilingual interpreter and tutor for Korean and English.\n" +
        "- The user may speak in Korean or English.\n" +
        "- ALWAYS respond in fluent, natural English.\n" +
        "- If the user speaks Korean, briefly interpret their intent into English in your own words, then provide a helpful English explanation or answer.\n" +
        "- If the user speaks English, respond as a supportive English tutor.\n" +
        "- Use SHORT English backchannels like \"mm-hmm\", \"let me think\", \"okay\" while thinking or listening.\n" +
        "- When the user asks about an uploaded image, first summarize what the question in the image is asking, then explain step-by-step in English."
      );
    }
  } else {
    // NORMAL TUTOR MODE
    if (targetLang === "ko") {
      return (
        "You are a kind Korean tutor.\n" +
        "- Speak in natural, polite Korean (존댓말).\n" +
        "- The user may ask in Korean or English; answer in Korean.\n" +
        "- Use SHORT Korean backchannels like \"음…\", \"그렇군요\", \"잠시만요\" while thinking.\n" +
        "- Give clear, step-by-step explanations and examples.\n" +
        "- When the user asks about an uploaded image, carefully explain what the question is asking and how to approach it."
      );
    } else {
      return (
        "You are a kind English tutor.\n" +
        "- Speak in natural, friendly English.\n" +
        "- The user may ask in Korean or English; answer in English.\n" +
        "- Use SHORT English backchannels like \"mm-hmm\", \"let me think\", \"okay\" while thinking.\n" +
        "- Give clear, step-by-step explanations and examples.\n" +
        "- When the user asks about an uploaded image, carefully explain what the question is asking and how to approach it."
      );
    }
  }
}

// ------------------------------
// Image upload → data URL
// ------------------------------
function handleImageFile(file) {
  if (!file || !file.type.startsWith("image/")) {
    uploadedImageUrl = null;
    imageStatus.textContent = "No image selected.";
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    // reader.result is "data:image/...;base64,...."
    uploadedImageUrl = reader.result;
    imageStatus.textContent = `✅ Image ready: ${file.name}`;
    log("📷 Image loaded and ready.");
  };
  reader.readAsDataURL(file);
}

// Click to upload
uploadArea.addEventListener("click", () => {
  imageInput.click();
});

// Drag and drop
uploadArea.addEventListener("dragover", (e) => {
  e.preventDefault();
  uploadArea.classList.add("dragover");
});

uploadArea.addEventListener("dragleave", () => {
  uploadArea.classList.remove("dragover");
});

uploadArea.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadArea.classList.remove("dragover");
  const files = e.dataTransfer.files;
  if (files.length > 0) {
    handleImageFile(files[0]);
  }
});

imageInput.addEventListener("change", () => {
  handleImageFile(imageInput.files[0]);
});

// ------------------------------
// Buttons
// ------------------------------
startBtn.onclick = async () => {
  startBtn.disabled = true;
  try {
    await startRealtimeSession();
  } catch (err) {
    console.error(err);
    log("❌ Error starting session: " + err);
    startBtn.disabled = false;
    setStatus("error");
  }
};

stopBtn.onclick = () => {
  stopSession();
};

function stopSession() {
  if (pc) {
    pc.ontrack = null;
    pc.onicecandidate = null;
    pc.close();
  }
  if (localStream) {
    localStream.getTracks().forEach((t) => t.stop());
  }
  
  // Clear any pending speech stop timeout
  if (speechStopTimeout) {
    clearTimeout(speechStopTimeout);
    speechStopTimeout = null;
  }
  
  pc = null;
  dc = null;
  localStream = null;

  stopBtn.disabled = true;
  startBtn.disabled = false;
  setStatus("idle");
  log("🛑 Session stopped");
}

// ------------------------------
// Start Realtime Session
// ------------------------------
async function startRealtimeSession() {
  setStatus("starting…");
  log("Requesting ephemeral realtime token from /realtime-token…");

  const tokenResp = await fetch("/realtime-token", { method: "POST" });
  const tokenData = await tokenResp.json();
  if (!tokenResp.ok) {
    throw new Error("Failed to get client secret: " + JSON.stringify(tokenData));
  }
  clientSecret = tokenData.client_secret;
  log("✅ Got ephemeral client secret (hidden).");

  // 1) Get mic
  localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  log("🎙️ Microphone access granted.");

  // 2) Create RTCPeerConnection
  pc = new RTCPeerConnection();
  setStatus("connecting…");
  stopBtn.disabled = false;

  // 3) Attach local audio
  localStream.getTracks().forEach((track) => {
    pc.addTrack(track, localStream);
  });

  // 4) Remote audio from model
  pc.ontrack = (event) => {
    log("🔊 Received remote track from model.");
    remoteAudio.srcObject = event.streams[0];
  };

  // 5) Data channel for events
  dc = pc.createDataChannel("oai-events");
  dc.onopen = () => {
    log("📡 DataChannel open.");
    // Send initial language instructions
    sendSessionUpdate();

    // If user uploaded an image before, send it as a conversation item
    if (uploadedImageUrl) {
      sendImageToRealtime(uploadedImageUrl);
    }
  };

  dc.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleServerEvent(msg);
    } catch (e) {
      log("📨 DataChannel message: " + event.data);
    }
  };

  pc.onicecandidate = (event) => {
    if (event.candidate) {
      log("ICE candidate generated.");
    }
  };

  pc.onconnectionstatechange = () => {
    log("RTCPeerConnection state: " + pc.connectionState);
    if (pc.connectionState === "connected") {
      setStatus("connected");
      log("✅ WebRTC connected. Start talking!");
    } else if (
      pc.connectionState === "failed" ||
      pc.connectionState === "disconnected"
    ) {
      setStatus(pc.connectionState);
    }
  };

  // 6) Create SDP offer
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  log("📃 Local SDP created.");

  // 7) Build initial session config
  const targetLang = getTargetLanguage();
  const translatorMode = isTranslatorMode();
  const instructions = buildInstructions(targetLang, translatorMode);

  const sessionConfig = {
    type: "realtime",
    instructions,
  };

  // 8) Send SDP + session config to Realtime Calls API
  const fd = new FormData();
  fd.set("sdp", offer.sdp);
  fd.set("session", JSON.stringify(sessionConfig));

  log("🔄 Sending offer to OpenAI /v1/realtime/calls…");
  const resp = await fetch(
    "https://api.openai.com/v1/realtime/calls?model=gpt-realtime",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${clientSecret}`,
      },
      body: fd,
    }
  );

  // The response might be JSON with { sdp: "..." } or SDP text directly
  const responseText = await resp.text();
  
  if (!resp.ok) {
    log("❌ /v1/realtime/calls error: " + responseText);
    throw new Error(responseText);
  }

  let sdpText;
  try {
    // Try parsing as JSON first
    const answer = JSON.parse(responseText);
    sdpText = answer.sdp || answer;
  } catch (e) {
    // If not JSON, assume it's SDP text directly
    sdpText = responseText;
  }
  
  await pc.setRemoteDescription({
    type: "answer",
    sdp: sdpText,
  });

  log("✅ Remote SDP set. Realtime session established.");
  setStatus("connected");
}

// ------------------------------
// Language toggle → session.update
// ------------------------------
document.querySelectorAll('input[name="lang"]').forEach((input) => {
  input.addEventListener("change", () => {
    if (dc && dc.readyState === "open") {
      sendSessionUpdate();
    }
  });
});

// Translator mode toggle → session.update
if (translatorToggle) {
  translatorToggle.addEventListener("change", () => {
    if (dc && dc.readyState === "open") {
      sendSessionUpdate();
    }
  });
}

function sendSessionUpdate() {
  const targetLang = getTargetLanguage();
  const translatorMode = isTranslatorMode();
  const instructions = buildInstructions(targetLang, translatorMode);

  const evt = {
    type: "session.update",
    session: {
      type: "realtime",
      instructions,
    },
  };

  try {
    dc.send(JSON.stringify(evt));
    log(
      "📤 Sent session.update for language = " +
        targetLang +
        ", translatorMode = " +
        translatorMode
    );
  } catch (e) {
    log("❌ Failed to send session.update: " + e);
  }
}

// ------------------------------
// Tutor Notes Request
// ------------------------------
function requestTutorNotes() {
  const targetLang = getTargetLanguage();
  const translatorMode = isTranslatorMode ? isTranslatorMode() : false;
  // Build language-specific note style
  const notesInstruction =
    targetLang === "ko"
      ? "Summarize our tutoring session so far in polite Korean (존댓말). " +
        "Write concise study notes with bullet points. Include: (1) 핵심 개념, (2) 예시, (3) 자주 하는 실수, (4) 복습하면 좋은 포인트. " +
        "Do NOT speak these aloud; just return text notes."
      : "Summarize our tutoring session so far in clear English. " +
        "Write concise study notes with bullet points. Include: (1) key concepts, (2) examples, (3) common mistakes, (4) suggested review topics. " +
        "Do NOT speak these aloud; just return text notes.";

  const evt = {
    type: "response.create",
    response: {
      // We want text-only notes (no voice)
      modalities: ["text"],
      // Mark this so we can route its output separately
      metadata: {
        topic: "tutor_notes",
      },
      instructions: notesInstruction,
    },
  };

  try {
    // Optionally clear previous notes so you see the latest version
    clearNotes();
    dc.send(JSON.stringify(evt));
    log("📑 Requested Tutor Notes via response.create.");
  } catch (e) {
    log("❌ Failed to send tutor notes request: " + e);
  }
}

// Wire the "Update Notes" button
if (updateNotesBtn) {
  updateNotesBtn.addEventListener("click", () => {
    if (!dc || dc.readyState !== "open") {
      log("⚠️ Cannot update notes: session not connected.");
      return;
    }
    requestTutorNotes();
  });
}

// ------------------------------
// Send uploaded image as context
// ------------------------------
function sendImageToRealtime(dataUrl) {
  // Realtime image input uses conversation.item.create with input_image content. :contentReference[oaicite:2]{index=2}
  const evt = {
    type: "conversation.item.create",
    previous_item_id: null,
    item: {
      type: "message",
      role: "user",
      content: [
        {
          type: "input_image",
          image_url: dataUrl,
        },
      ],
    },
  };

  try {
    dc.send(JSON.stringify(evt));
    log("📷 Sent input_image to Realtime model.");
    log("Now you can ask: \"Can you explain the question in the image I uploaded?\"");
  } catch (e) {
    log("❌ Failed to send image: " + e);
  }
}

// ------------------------------
// Handle server events
// ------------------------------
function handleServerEvent(msg) {
  if (msg.type === "conversation.item.created") {
    // You can inspect created items if you want, but not needed for notes.
    // log("Item created: " + JSON.stringify(msg.item));

  } else if (msg.type === "response.created") {
    // Tag this response as tutor notes if metadata says so
    const r = msg.response;
    if (r && r.metadata && r.metadata.topic === "tutor_notes") {
      responseKinds[r.id] = "tutor_notes";
      log("📝 Tutor Notes response.created (id=" + r.id + ")");
    }

  } else if (msg.type === "response.output_text.delta") {
    const kind = responseKinds[msg.response_id];
    if (kind === "tutor_notes") {
      if (msg.delta) {
        appendToNotes(msg.delta);
      }
    } else {
      // Normal model text stream
      if (msg.delta) {
        log("🧠 MODEL (delta): " + msg.delta);
      }
    }

  } else if (msg.type === "response.done" || msg.type === "response.completed") {
    // Response finished
    const kind = responseKinds[msg.response_id];
    if (kind === "tutor_notes") {
      log("✅ Tutor Notes generation completed.");
    } else {
      log("✅ MODEL response completed.");
      // OPTIONAL: auto-refresh notes after each normal response:
      // requestTutorNotes();
    }

  } else if (msg.type === "input_audio_buffer.speech_started") {
    // Clear any pending speech stop timeout since speech has started again
    if (speechStopTimeout) {
      clearTimeout(speechStopTimeout);
      speechStopTimeout = null;
    }
    log("👂 Detected user speech start.");
  } else if (msg.type === "input_audio_buffer.speech_stopped") {
    // Clear any existing timeout
    if (speechStopTimeout) {
      clearTimeout(speechStopTimeout);
    }
    
    // Set a new timeout - only log speech stop after the delay period
    speechStopTimeout = setTimeout(() => {
      log("👂 Detected user speech stop (after " + (SPEECH_STOP_DELAY_MS / 1000) + "s silence).");
      speechStopTimeout = null;
    }, SPEECH_STOP_DELAY_MS);
  } else if (msg.type === "session.updated") {
    log("ℹ️ Session updated.");
  } else if (msg.type === "error") {
    log("❌ Realtime error: " + JSON.stringify(msg));
  } else {
    // Uncomment for full debugging:
    // log("Event: " + JSON.stringify(msg));
  }
}
