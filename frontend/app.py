import streamlit as st
import requests

# 🔥 Page Config
st.set_page_config(
    page_title="AI Powered PDF SUMMARIZER",
    layout="wide",
    page_icon="📄"
)

# 🎨 Custom CSS Styling
st.markdown("""
<style>

/* Assistant message (AI response) */
[data-testid="stChatMessage"][data-testid="stChatMessage"] div {
    background-color: white !important;
    color: black !important;
    border-radius: 12px;
    padding: 10px;
}

/* Keep user message blue */
[data-testid="stChatMessage"]:nth-child(odd) {
    background-color: #00c6ff !important;
    color: white !important;
}

</style>
""", unsafe_allow_html=True)
# 🔥 Title
st.title("📄 AI-Powered PDF Summarizer")

# Chat memory
if "messages" not in st.session_state:
    st.session_state.messages = []

# 📂 Upload Section
st.markdown("### 📤 Upload your PDF")

pdf = st.file_uploader("", type="pdf")

if pdf:
    col1, col2 = st.columns([1, 2])

    with col1:
        if st.button("🚀 Process PDF"):
            with st.spinner("Processing PDF... ⏳"):
                try:
                    res = requests.post(
                        "http://127.0.0.1:8000/upload_pdf",
                        files={"file": (pdf.name, pdf.getvalue(), "application/pdf")}
                    )

                    if res.status_code == 200:
                        data = res.json()
                        st.success(data.get("message", "Done"))
                    else:
                        st.error(res.text)

                except:
                    st.error("❌ Backend not running")

# 💬 Chat Section
st.markdown("### 💬 Chat with your PDF")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# Ask question
question = st.chat_input("Ask anything from your document...")

if question:
    st.session_state.messages.append({"role": "user", "content": question})

    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("🤖 Thinking..."):
            try:
                res = requests.post(
                    "http://127.0.0.1:8000/ask",
                    data={"question": question}
                )

                if res.status_code == 200:
                    data = res.json()
                    answer = data.get("answer", "No response")
                else:
                    answer = "❌ Error from server"

            except:
                answer = "❌ Backend not running"

            st.write(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})