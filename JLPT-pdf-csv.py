import fitz  # PyMuPDF
import csv
import re
import os

def extract_listening_questions(pdf_path, watermark_texts=[]):
    """
    Extracts listening comprehension questions from the script PDF.

    Args:
        pdf_path (str): The path to the listening script PDF file.
        watermark_texts (list): A list of strings to be considered watermarks.

    Returns:
        list: A list of dictionaries, where each dictionary is a question.
    """
    questions = []
    try:
        doc = fitz.open(pdf_path)
        question_start_re = re.compile(r'^\d+番')
        current_question_data = None
        full_dialogue = ""

        for page_num, page in enumerate(doc):
            blocks = page.get_text("blocks")
            for b in blocks:
                block_text = b[4].strip()

                if any(wt in block_text for wt in watermark_texts):
                    continue

                if question_start_re.match(block_text):
                    if current_question_data:
                        dialogue_parts = full_dialogue.strip().split('\n')
                        if len(dialogue_parts) > 1:
                            current_question_data["question"] = dialogue_parts[-1]
                            current_question_data["dialogue"] = "\n".join(dialogue_parts[:-1])
                        else:
                            current_question_data["question"] = full_dialogue.strip()
                            current_question_data["dialogue"] = ""
                        questions.append(current_question_data)
                    
                    current_question_data = {
                        "type": "Listening",
                        "number": block_text.split('\n')[0],
                        "source_page": page_num + 1
                    }
                    full_dialogue = block_text.split('\n', 1)[-1] + "\n"
                elif current_question_data:
                    full_dialogue += block_text + "\n"
        
        if current_question_data:
            dialogue_parts = full_dialogue.strip().split('\n')
            if len(dialogue_parts) > 1:
                current_question_data["question"] = dialogue_parts[-1]
                current_question_data["dialogue"] = "\n".join(dialogue_parts[:-1])
            else:
                current_question_data["question"] = full_dialogue.strip()
                current_question_data["dialogue"] = ""
            questions.append(current_question_data)

    except Exception as e:
        print(f"An error occurred while processing {pdf_path}: {e}")
    
    print(f"Found {len(questions)} listening questions.")
    return questions

def extract_grammar_vocab_questions(pdf_path, watermark_texts=[]):
    """
    Extracts vocabulary and grammar questions from the answer key PDF.
    This version uses a robust method to detect underlines, including those
    drawn as thin rectangles, to correctly identify answers.

    Args:
        pdf_path (str): The path to the answer key PDF file.
        watermark_texts (list): A list of strings to be considered watermarks.

    Returns:
        list: A list of dictionaries, where each dictionary is a question.
    """
    questions = []
    
    # --- New, more robust underline detection logic ---
    def get_underlines(page):
        """
        Finds all vector graphics on a page that look like underlines.
        This includes both horizontal lines and thin rectangles.
        """
        underlines = []
        drawings = page.get_drawings()
        for path in drawings:
            for item in path["items"]:
                # 'l' is a line command
                if item[0] == "l":
                    p1, p2 = item[1], item[2]
                    # Check if it's a nearly horizontal line
                    if abs(p1.y - p2.y) <= 2:
                        underlines.append(fitz.Rect(p1, p2))
                # 're' is a rectangle command
                elif item[0] == "re":
                    rect = fitz.Rect(item[1])
                    # Check if it's a thin rectangle (acting as a line)
                    if rect.height <= 2 and rect.width > 0:
                        underlines.append(rect)
        return underlines

    def is_span_marked(span, underlines):
        """
        Checks if a text span is marked as an answer, either by being
        bold or by having an underline shape geometrically close to it.
        """
        span_rect = fitz.Rect(span['bbox'])
        
        # 1. Check for the standard 'bold' font flag.
        if span['flags'] & 16:
            return True
            
        # 2. Check for a geometric underline.
        span_mid_x = (span_rect.x0 + span_rect.x1) / 2
        span_baseline_y = span_rect.y1
        
        for r in underlines:
            # Check if the text's horizontal midpoint is within the underline's range
            # and if the underline is vertically close to and below the text's baseline.
            # Increased vertical tolerance to 4 for more reliability.
            if (r.x0 <= span_mid_x <= r.x1) and (0 <= (r.y0 - span_baseline_y) < 4):
                return True
                
        return False
    # --- End of helper functions ---

    def process_and_save_grammar_question(data, page_underlines):
        if not data:
            return None
        
        full_sentence = ""
        answer_text = ""

        for line_spans in data['spans']:
            for span in line_spans:
                full_sentence += span['text']
                if is_span_marked(span, page_underlines):
                    answer_text += span['text']
            full_sentence += '\n'
        
        full_sentence = full_sentence.strip()
        answer_text = answer_text.strip()

        if answer_text:
            question_text = full_sentence.replace(answer_text, " (______) ", 1)
        else:
            question_text = full_sentence

        question_text = re.sub(r'^\d+\.\s*', '', question_text).strip()

        q = {
            "type": "Grammar/Reading",
            "number": data['number'],
            "question": question_text,
            "answer": answer_text,
            "source_page": data['page'],
            "dialogue": "", "choices": ""
        }
        questions.append(q)

    try:
        doc = fitz.open(pdf_path)
        section = "vocab"
        current_mondai = 0
        current_grammar_q_data = None

        for page_num, page in enumerate(doc):
            underlines = get_underlines(page)
            text_dict = page.get_text("dict")
            
            for block in text_dict['blocks']:
                if 'lines' not in block:
                    continue
                
                for line in block['lines']:
                    line_text = "".join([span['text'] for span in line['spans']]).strip()
                    
                    if any(wt in line_text for wt in watermark_texts):
                        continue

                    if "もじ・ごい" in line_text:
                        section = "vocab"
                        process_and_save_grammar_question(current_grammar_q_data, underlines)
                        current_grammar_q_data = None
                        continue
                    elif "ぶんぽう・どっかい" in line_text:
                        section = "grammar"
                        continue

                    mondai_match = re.match(r'問題(\d+)', line_text)
                    if mondai_match:
                        current_mondai = int(mondai_match.group(1))
                        process_and_save_grammar_question(current_grammar_q_data, underlines)
                        current_grammar_q_data = None
                        continue

                    if not current_mondai or not line_text:
                        continue
                    
                    q = {"dialogue": "", "question": "", "choices": "", "answer": "", "source_page": page_num + 1}
                    
                    if section == "grammar":
                        is_new_question = re.match(r'^(\d+)\.', line_text)
                        if is_new_question:
                            process_and_save_grammar_question(current_grammar_q_data, underlines)
                            current_grammar_q_data = {
                                'number': is_new_question.group(1),
                                'spans': [line['spans']], 'page': page_num + 1
                            }
                        elif current_grammar_q_data:
                            current_grammar_q_data['spans'].append(line['spans'])
                    else:
                        if current_mondai == 3 and re.match(r'^\d+\.', line_text):
                            full_sentence = ""
                            answer_text = ""
                            
                            for span in line['spans']:
                                full_sentence += span['text']
                                if is_span_marked(span, underlines):
                                    answer_text += span['text']
                            
                            answer_text = answer_text.strip()
                            
                            if answer_text:
                                question_text = full_sentence.replace(answer_text, " (______) ", 1)
                            else:
                                question_text = full_sentence
                            
                            question_text = re.sub(r'^\d+\.\s*', '', question_text).strip()

                            q.update({
                                'type': "Fill-in-the-Blank",
                                'number': line_text.split('.')[0],
                                'answer': answer_text,
                                'question': question_text
                            })
                            questions.append(q)
                        elif current_mondai in [1, 2] and '「' in line_text:
                            match = re.search(r'(\d+)\.(.*)「(.*)」', line_text)
                            if match:
                                q.update({
                                    'type': "Vocabulary (Kanji/Kana)", 'number': match.group(1),
                                    'question': match.group(2).strip(), 'answer': match.group(3).strip()
                                })
                                questions.append(q)
                        elif current_mondai == 4 and '=' in line_text:
                            parts = line_text.split('=', 1)
                            if len(parts) == 2:
                                q.update({
                                    'type': "Synonym", 'number': parts[0].split('.')[0].strip(),
                                    'question': parts[0].split('.', 1)[1].strip(), 'answer': parts[1].strip()
                                })
                                questions.append(q)
                        elif current_mondai == 5 and '⇒' in line_text:
                            parts = line_text.split('⇒', 1)
                            if len(parts) == 2:
                                q.update({
                                    'type': "Sentence Construction", 'number': parts[0].strip(),
                                    'question': parts[0].strip(), 'answer': parts[1].strip()
                                })
                                questions.append(q)

        process_and_save_grammar_question(current_grammar_q_data, underlines)

    except Exception as e:
        print(f"An error occurred while processing {pdf_path}: {e}")

    print(f"Found {len(questions)} grammar/vocabulary questions.")
    return questions


# --- Main Execution ---
if __name__ == "__main__":
    # --- Configuration ---
    listening_pdf = "./question-bank/2024_N4_Listening.pdf"
    grammar_pdf = "./question-bank/2024_N4_Grammar.pdf"
    output_csv = "jlpt_question_database.csv"
    watermark_texts = ["Mogi", "Bùi", "Script Nghe", "YuukiBùi", "N4答案"]

    # --- File Existence Check ---
    if not os.path.exists(listening_pdf) or not os.path.exists(grammar_pdf):
        print("Error: Make sure both PDF files are in the same directory as the script:")
        print(f"- {listening_pdf}")
        print(f"- {grammar_pdf}")
    else:
        # --- Extraction ---
        print("Starting question extraction...")
        listening_q = extract_listening_questions(listening_pdf, watermark_texts)
        grammar_q = extract_grammar_vocab_questions(grammar_pdf, watermark_texts)
        
        all_questions = listening_q + grammar_q

        # --- Writing to CSV ---
        if not all_questions:
            print("No questions were extracted. Please check the PDF files and script.")
        else:
            try:
                with open(output_csv, 'w', newline='', encoding='utf-8-sig') as csvfile:
                    fieldnames = ['type', 'number', 'dialogue', 'question', 'choices', 'answer', 'source_page']
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(all_questions)
                
                print(f"\nSuccess! Extracted {len(all_questions)} total questions.")
                print(f"Database saved to: {output_csv}")
            except Exception as e:
                print(f"\nAn error occurred while writing to CSV: {e}")
