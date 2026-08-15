'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit

GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Support me: https://github.com/sponsors/GodsScion

'''

import os
from modules.helpers import print_lg


def extract_resume_text(path: str) -> str:
    '''
    Extracts and returns the plain text content of a resume file (.pdf, .docx or .txt).
    Returns "" if the file doesn't exist, is an unsupported format, or fails to parse
    (e.g. a scanned/image-only PDF with no extractable text) - callers should treat
    that as "no resume text available" rather than an error.
    '''
    if not path or not os.path.isfile(path):
        return ""
    extension = os.path.splitext(path)[1].lower()
    try:
        if extension == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(path)
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        elif extension == ".docx":
            import docx
            document = docx.Document(path)
            return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
        elif extension == ".txt":
            with open(path, "r", encoding="utf-8", errors="ignore") as file:
                return file.read().strip()
        else:
            print_lg(f'Unsupported resume format "{extension}" for AI context, skipping. Supported formats: .pdf, .docx, .txt')
            return ""
    except Exception as e:
        print_lg(f'Failed to extract text from resume "{path}" for AI context.', e)
        return ""
