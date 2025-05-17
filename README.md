# Instructions for Bravur's AI Chatbot 

## Prerequisites:
- PyCharm Installed or Install Python
- Node.js installed (for Husky and CommitLint)

## Clone the repository:
```bash
git clone https://github.com/SaraBubanova/Bravurs_AI_Chatbot.git
cd Bravurs_AI_Chatbot
```

## Drag .env file into root directory (on Teams, deliverables folder)
This project requires a `.env` file containing necessary API keys and database connection details.

*   **Locate the `.env` file:** Please find this file in the shared location provided by the team (e.g., check the 'Deliverables' folder on Microsoft Teams or ask a team lead).
*   **Place the file:** Copy or move the `.env` file directly into the root `Bravurs_AI_Chatbot` directory (this is the folder you cloned in Step 1 and then used `cd` to enter).

## Create a virtual environment
```bash
python -m venv venv
```
Or a PyCharm asks you to create an interpreter using the requirements.txt file (Click Yes)

# Activate the virtual environment
# On Windows:
```bash
venv\Scripts\activate
```
# On macOS/Linux:
```bash
source venv/bin/activate
```

## Install dependencies
```bash
pip install -r requirements.txt
```

## Install Git commit hooks (Husky + CommitLint)
This project uses Husky to enforce proper commit messages.

Run the following command in the project root:
```bash
npm install
```
This will automatically install Husky and set up CommitLint hooks.

## Run the App
```bash
python run.py
```





