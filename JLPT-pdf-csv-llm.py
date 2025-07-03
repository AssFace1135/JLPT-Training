import fitz  # PyMuPDF
import csv
import re
import os
import json
from dotenv import load_dotenv
import google.generativeai as genai

def configure_api():
    """Loads the API key from .env and configures the Gemini API."""
    load_dotenv()
    api_key = os.getenv("Gemini_api_key")
    if not api_key:
        raise ValueError("Gemini_api_key not found in .env file. Please ensure it is set correctly.")
    # The key in the .env file has quotes, so we strip them.
    genai.configure(api_key=api_key.strip("'"))

def clean_llm_response(text):
    """Cleans the LLM's response to extract the JSON part."""
    # Find the JSON block within the markdown code fence
    match = re.search(r'```(json)?(.*)```', text, re.DOTALL)
    if match:
        return match.group(2).strip()
    # If no markdown fence, assume the whole text is the JSON
    return text.strip()

def get_llm_prompt(page_text, page_num):
    """Creates the detailed prompt for the LLM to extract questions."""
    return f"""
You are an expert assistant specializing in parsing Japanese Language Proficiency Test (JLPT) documents.
Your task is to analyze the text from a single page of a JLPT practice test PDF and extract all the questions into a structured format.

The text may contain various question types, including:
- Vocabulary (e.g., reading of a kanji word)
- Fill-in-the-blank grammar questions.
- Sentence construction problems.
- Synonym identification.

The answer to a question is often underlined or bolded within the sentence. For fill-in-the-blank questions, the question text should contain a placeholder like `(______)` where the answer was.

Please analyze the following page text and return a JSON array of question objects.

**RULES:**
1.  Each object in the array must represent a single question.
2.  Each object must have these exact keys: "type", "number", "dialogue", "question", "choices", "answer", "source_page".
3.  "type": A short description of the question type (e.g., "Vocabulary", "Fill-in-the-Blank", "Synonym").
4.  "number": The question number as a string (e.g., "1", "2").
5.  "dialogue": Any conversational text leading up to the question. If none, use an empty string.
6.  "question": The main text of the question. For fill-in-the-blanks, the original sentence with the answer replaced by `(______)`.
7.  "choices": A string containing the multiple-choice options, separated by newlines. If none, use an empty string.
8.  "answer": The correct answer text.
9.  "source_page": The page number provided to you.
10. If the page contains no questions, return an empty JSON array `[]`.
11. Your entire response must be ONLY the JSON array, with no other text, explanations, or markdown formatting.

**Page Number:** {page_num}

**Page Text:**
---
{page_text}
---
"""

def extract_questions_with_llm(pdf_path, watermark_texts=[]):
    """
    Extracts questions from a PDF using an LLM.

    It iterates through each page, sends the text to the Gemini API,
    and parses the structured JSON response.
    """
    all_questions = []
    try:
        configure_api()
        # The 'gemini-pro' model name can sometimes cause a 404 error with certain API versions.
        # Using a more specific version like 'gemini-1.0-pro' is more reliable.
        # For potentially faster and cheaper results, you could also try 'gemini-1.5-flash-latest'.
        model = genai.GenerativeModel('gemini-2.5-flash')
        doc = fitz.open(pdf_path)

        print(f"Processing {len(doc)} pages from '{pdf_path}'...")

        for page_num, page in enumerate(doc, 1):
            print(f"  - Analyzing page {page_num}/{len(doc)}...")
            page_text = page.get_text("text")

            # Basic cleaning and watermark removal
            lines = []
            for line in page_text.split('\n'):
                if not any(wt in line for wt in watermark_texts):
                    lines.append(line)
            cleaned_text = "\n".join(lines)

            if not cleaned_text.strip():
                continue

            prompt = get_llm_prompt(cleaned_text, page_num)
            response = model.generate_content(prompt)

            try:
                json_text = clean_llm_response(response.text)
                page_questions = json.loads(json_text)
                if page_questions:
                    print(f"    -> Found {len(page_questions)} questions on this page.")
                    all_questions.extend(page_questions)
            except (json.JSONDecodeError, AttributeError) as e:
                print(f"    -> WARNING: Could not parse LLM response for page {page_num}. Error: {e}")
                print(f"       LLM Response was: {response.text[:200]}...") # Log snippet of bad response

    except Exception as e:
        print(f"An error occurred during LLM extraction: {e}")

    return all_questions

#==============================================================================
# MAIN WORKFLOW
#==============================================================================

if __name__ == "__main__":
    # --- Configuration ---
    grammar_pdf = "./question-bank/2024_N4_Grammar.pdf"
    output_csv = "jlpt_database_llm_generated.csv"
    watermark_texts = ["Mogi", "Bùi", "Script Nghe", "YuukiBùi", "N4答案"]

    print("Starting LLM-powered PDF Extraction...")
    if not os.path.exists(grammar_pdf):
        print(f"Error: The PDF file was not found at '{grammar_pdf}'")
    else:
        extracted_questions = extract_questions_with_llm(grammar_pdf, watermark_texts)

        if not extracted_questions:
            print("\nNo questions were extracted. This could be due to an API issue or an empty document.")
        else:
            try:
                with open(output_csv, 'w', newline='', encoding='utf-8-sig') as csvfile:
                    fieldnames = ['type', 'number', 'dialogue', 'question', 'choices', 'answer', 'source_page']
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(extracted_questions)

                print(f"\nSuccess! LLM extraction complete.")
                print(f"Generated {len(extracted_questions)} questions in '{output_csv}'.")
                print("Please review the generated CSV file for accuracy.")

            except Exception as e:
                print(f"\nAn error occurred while writing the CSV file: {e}")
