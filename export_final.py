#!/usr/bin/env python3
"""Export final book in all formats"""
import asyncio
import sys
from pathlib import Path

# Add project path
sys.path.insert(0, '/Users/guoquan/work/Kimi/biography_writer')

from src.engine import BiographyEngine
from src.models import WritingStyle

async def main():
    engine = BiographyEngine()
    
    # Load existing project
    book_id = "bade1b72b4fc16cd"
    print(f"Loading project: {book_id}")
    
    if not engine.load_project(book_id):
        print("Failed to load project")
        return
    
    print("Project loaded successfully")
    
    # Generate book from reviewed chapters
    print("Generating book from reviewed chapters...")
    book = await engine.generate_book()
    
    print(f"Book generated: {book.title}")
    print(f"  - Chapters: {len(book.chapters)}")
    print(f"  - Total words: {book.total_word_count}")
    
    # Export in all formats
    print("\nExporting in all formats...")
    exported = await engine.save_book(
        book=book,
        formats=["txt", "md", "json", "epub"],
        use_version_selection=True
    )
    
    print("\n✅ Export completed!")
    print("\nExported files:")
    for fmt, path in exported.items():
        if fmt != "chapters_dir":
            print(f"  {fmt}: {path}")

if __name__ == "__main__":
    asyncio.run(main())
