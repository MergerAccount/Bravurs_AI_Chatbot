# 🧠 Bravur's AI Chatbot – Backend

This is the backend for Bravur's AI Chatbot, a Python-based API that connects with a WordPress plugin frontend. It handles all the logic and data processing for the chatbot.

---

## ✅ Prerequisites

Before you begin, ensure you have the following installed:

- [Python 3.x](https://www.python.org/downloads/)
- [PyCharm (optional)](https://www.jetbrains.com/pycharm/) – or any Python IDE
- [Node.js](https://nodejs.org/) – required for Git hooks via Husky and CommitLint

---

## 📥 Clone the Repository
```bash
git clone https://github.com/MergerAccount/Bravurs_AI_Chatbot.git
cd Bravurs_AI_Chatbot
```


## 🔐 Add the .env File

This project uses environment variables to store sensitive information like API keys and database connection details.

Locate the file:
The .env file is available in the shared deliverables folder on Microsoft Teams. Ask the team leader if you can’t find it.

Copy it to your project root:
Drag and drop the .env file into the root of the cloned Bravurs_AI_Chatbot directory — the same folder you ran the cd command in above.

```bash
📁 Bravurs_AI_Chatbot/
├── .env            ← You'll need to add this
├── venv/
├── requirements.txt
└── ...
```

⚠️ The .env file is not tracked in Git, so each developer must add it manually.


## 🐍 Create and Activate a Virtual Environment

### Step 1

```bash
python -m venv venv
```

Or: If PyCharm prompts you to create an interpreter using requirements.txt, click Yes.

### Step 2


On Windows:
```bash
venv\Scripts\activate
```

On macOS/Linux:
```bash
source venv/bin/activate
```


### Install Python Dependencis

```bash 
pip install -r requirements.txt
```

This will install Husky and configure the Git hooks automatically.

# ▶️Run the App

```bash
python run.py
```

# 🧪 Testing 
You can test the backend independently by visiting an endpoint in the browser or using tools like Postman or curl:

```bash
curl http://localhost:5001/api/v1
```