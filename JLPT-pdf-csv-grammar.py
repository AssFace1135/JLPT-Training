import fitz  # PyMuPDF
import csv
import re
import os

#==============================================================================
# STAGE 1: AUTOMATED PDF EXTRACTION
#==============================================================================

def extract_grammar_vocab_questions(pdf_path, watermark_texts=[]):
    """
    Performs the initial automated extraction of questions from the grammar/vocab PDF.
    It tries to detect answers automatically to create a first draft.
    """
    questions = []
    
    def get_underlines(page):
        underlines = []
        drawings = page.get_drawings()
        for path in drawings:
            for item in path["items"]:
                if item[0] == "l":
                    p1, p2 = item[1], item[2]
                    if abs(p1.y - p2.y) <= 2: underlines.append(fitz.Rect(p1, p2))
                elif item[0] == "re":
                    rect = fitz.Rect(item[1])
                    if rect.height <= 2 and rect.width > 0: underlines.append(rect)
        return underlines

    def is_span_marked(span, underlines):
        span_rect = fitz.Rect(span['bbox'])
        if span['flags'] & 16: return True
        span_mid_x = (span_rect.x0 + span_rect.x1) / 2
        span_baseline_y = span_rect.y1
        for r in underlines:
            if (r.x0 <= span_mid_x <= r.x1) and (0 <= (r.y0 - span_baseline_y) < 4):
                return True
        return False

    def process_and_save_question(data, page_underlines):
        if not data: return
        
        full_sentence, answer_text = "", ""
        for line_spans in data['spans']:
            for span in line_spans:
                full_sentence += span['text']
                if is_span_marked(span, page_underlines):
                    answer_text += span['text']
            full_sentence += '\n'
        
        full_sentence = full_sentence.strip()
        answer_text = answer_text.strip()
        question_text = re.sub(r'^\d+\.\s*', '', full_sentence).strip()

        questions.append({
            "type": data['type'], "number": data['number'],
            "question": question_text, "answer": answer_text,
            "source_page": data['page'], "dialogue": "", "choices": ""
        })

    try:
        doc = fitz.open(pdf_path)
        section, current_mondai, current_question_data = "vocab", 0, None

        for page_num, page in enumerate(doc):
            underlines = get_underlines(page)
            text_dict = page.get_text("dict")
            
            for block in text_dict['blocks']:
                if 'lines' not in block: continue
                for line in block['lines']:
                    line_text = "".join([span['text'] for span in line['spans']]).strip()
                    if any(wt in line_text for wt in watermark_texts): continue

                    if "もじ・ごい" in line_text:
                        section = "vocab"
                        process_and_save_question(current_question_data, underlines)
                        current_question_data = None
                        continue
                    elif "ぶんぽう・どっかい" in line_text:
                        section = "grammar"
                        continue

                    mondai_match = re.match(r'問題(\d+)', line_text)
                    if mondai_match:
                        current_mondai = int(mondai_match.group(1))
                        process_and_save_question(current_question_data, underlines)
                        current_question_data = None
                        continue

                    if not current_mondai or not line_text: continue
                    
                    q_type = "Grammar/Reading" if section == "grammar" else "Fill-in-the-Blank"
                    is_new_question = re.match(r'^(\d+)\.', line_text)
                    if is_new_question:
                        process_and_save_question(current_question_data, underlines)
                        current_question_data = {
                            'type': q_type, 'number': is_new_question.group(1),
                            'spans': [line['spans']], 'page': page_num + 1
                        }
                    elif current_question_data:
                        current_question_data['spans'].append(line['spans'])
        process_and_save_question(current_question_data, underlines)
    except Exception as e:
        print(f"An error occurred during automated extraction: {e}")
    return questions

#==============================================================================
# STAGE 2: MANUAL REFINEMENT
#==============================================================================

def refine_with_manual_answers(manual_csv_path, final_csv_path):
    """
    Reads the manually corrected CSV, reformats the questions based on the
    provided answers, and saves the final, perfect database.
    """
    try:
        with open(manual_csv_path, 'r', newline='', encoding='utf-8-sig') as infile, \
             open(final_csv_path, 'w', newline='', encoding='utf-8-sig') as outfile:
            
            reader = csv.DictReader(infile)
            # The fieldnames are now read directly from the manual file,
            # preserving your desired column order.
            fieldnames = reader.fieldnames
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()
            
            count = 0
            for row in reader:
                question = row.get('question', '')
                answer = row.get('answer', '').strip()
                
                # If there's a manually provided answer, use it to format the question
                if answer and answer in question:
                    # Replace only the first occurrence of the answer
                    row['question'] = question.replace(answer, " (______) ", 1)
                
                writer.writerow(row)
                count += 1
        print(f"\nSuccessfully refined {count} questions based on your manual input.")
        print(f"Final database saved to: {final_csv_path}")

    except FileNotFoundError:
        print(f"Error: Manual correction file not found at '{manual_csv_path}'")
    except Exception as e:
        print(f"An error occurred during manual refinement: {e}")

#==============================================================================
# MAIN WORKFLOW
#==============================================================================

if __name__ == "__main__":
    # --- Configuration ---
    grammar_pdf = "./question-bank/2024_N4_Grammar.pdf"
    auto_output_csv = "jlpt_database_auto.csv"
    manual_input_csv = "jlpt_database_manual.csv"
    final_output_csv = "jlpt_database_final.csv"
    watermark_texts = ["Mogi", "Bùi", "Script Nghe", "YuukiBùi", "N4答案"]

    # --- Check if we are running refinement stage ---
    if os.path.exists(manual_input_csv):
        print("Manual correction file found. Starting Stage 2: Refinement...")
        refine_with_manual_answers(manual_input_csv, final_output_csv)
    
    # --- Otherwise, run the initial extraction stage ---
    else:
        print("Starting Stage 1: Automated Extraction...")
        if not os.path.exists(grammar_pdf):
            print(f"Error: The grammar PDF file was not found at '{grammar_pdf}'")
        else:
            grammar_questions = extract_grammar_vocab_questions(grammar_pdf, watermark_texts)
            
            if not grammar_questions:
                print("No questions were extracted from the PDF.")
            else:
                try:
                    with open(auto_output_csv, 'w', newline='', encoding='utf-8-sig') as csvfile:
                        # Set the fieldnames to the user's desired order
                        fieldnames = ['type', 'number', 'dialogue', 'question', 'choices', 'answer', 'source_page']
                        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
                        writer.writeheader()
                        writer.writerows(grammar_questions)
                    
                    print(f"\nSuccess! Automated extraction complete.")
                    print(f"Generated {len(grammar_questions)} questions in '{auto_output_csv}'.")
                    print("\n--- NEXT STEPS ---")
                    print(f"1. Copy '{auto_output_csv}' and rename the copy to '{manual_input_csv}'.")
                    print(f"2. Open '{manual_input_csv}' and correct the 'answer' column for any questions the script got wrong.")
                    print(f"3. Run this script again to generate the final, perfect database.")

                except Exception as e:
                    print(f"\nAn error occurred while writing the automated CSV: {e}")
