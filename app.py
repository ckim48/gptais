import uuid
import json
import os
import requests
from flask import Flask, render_template, request, send_file, session, redirect, url_for

from openai import OpenAI
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from io import BytesIO
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3

app = Flask(__name__)

app.secret_key = "secret_key_here"
STORY_JSON_PATH = "saved_data/story.json"
IMAGES_JSON_PATH = "saved_data/images.json"
IMAGE_DIR = "static/images"
DB_PATH = "projectgpt.db"



os.makedirs("saved_data", exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)

import json.decoder  # at the top if not already imported

@app.route("/download_pdf")
def download_pdf():
    if not os.path.exists(STORY_JSON_PATH):
        return "No storybook available to download."

    with open(STORY_JSON_PATH) as f:
        pages = json.load(f)

    images = []
    if os.path.exists(IMAGES_JSON_PATH):
        try:
            with open(IMAGES_JSON_PATH) as f:
                content = f.read().strip()
                if content:
                    images = json.loads(content)
        except json.decoder.JSONDecodeError:
            print("Warning: images.json is invalid or empty.")
            images = []
    # Ensure images list matches pages count
    if len(images) < len(pages):
        images += [None] * (len(pages) - len(images))

    # Continue as usual...
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(letter))

    width, height = landscape(letter)
    padding = 50
    gutter = 30
    text_box_x = padding
    text_box_y = height - padding
    text_box_width = (width - 2 * padding - gutter) * 0.5
    text_box_height = height - 2 * padding
    image_box_x = text_box_x + text_box_width + gutter
    image_box_y = padding
    image_box_width = text_box_width
    image_box_height = text_box_height

    for i, (text, img_path) in enumerate(zip(pages, images)):
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(padding, height - 30, f"Page {i + 1}")

        pdf.setFont("Times-Roman", 14)
        pdf.setFillColorRGB(0, 0, 0)
        text_obj = pdf.beginText(text_box_x, text_box_y - 40)
        text_obj.setLeading(22)
        for line in split_text(text, 80):
            if text_obj.getY() < padding:
                break
            text_obj.textLine(line)
        pdf.drawText(text_obj)

        if img_path:
            try:
                image_reader = ImageReader("." + img_path)
                pdf.drawImage(
                    image_reader,
                    image_box_x,
                    image_box_y,
                    width=image_box_width,
                    height=image_box_height,
                    preserveAspectRatio=True,
                    anchor='c'
                )
            except Exception as e:
                print(f"Could not load image {img_path}: {e}")

        pdf.showPage()

    pdf.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="storybook_clean_wide.pdf", mimetype='application/pdf')

def split_text(text, max_chars):
    words = text.split()
    lines, line = [], ""
    for word in words:
        if len(line + word) <= max_chars:
            line += word + " "
        else:
            lines.append(line.strip())
            line = word + " "
    lines.append(line.strip())
    return lines



@app.route("/storybook")
def storybook():
    pages, images = [], []
    if os.path.exists(STORY_JSON_PATH) and os.path.exists(IMAGES_JSON_PATH):
        with open(STORY_JSON_PATH) as f:
            pages = json.load(f)
        with open(IMAGES_JSON_PATH) as f:
            images = json.load(f)
    return render_template("story_detail.html", pages=pages, images=images)

def split_story_into_pages(story_text, max_chars_per_page=500):
    words = story_text.split()
    pages = []
    page = ""
    for word in words:
        if len(page) + len(word) + 1 > max_chars_per_page:
            pages.append(page.strip())
            page = ""
        page += word + " "
    if page:
        pages.append(page.strip())
    return pages

def generate_images_for_pages(pages, story_id):
    image_paths = []
    for i, page in enumerate(pages):
        prompt = f"Children's storybook illustration: {page[:150]}"
        try:
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                n=1,
                size="1024x1024"
            )
            image_url = response.data[0].url

            img_data = requests.get(image_url).content
            filename = f"{IMAGE_DIR}/story_{story_id}_page_{i+1}.png"
            with open(filename, "wb") as f:
                f.write(img_data)

            image_paths.append("/" + filename)
        except Exception as e:
            print(f"Image error on page {i+1}: {e}")
            image_paths.append("/static/images/default.jpg")
    return image_paths
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, password_hash FROM users WHERE email = ?", (email,))
            result = cursor.fetchone()

        if result and check_password_hash(result[2], password):
            session["user_id"] = result[0]
            session["username"] = result[1]
            return redirect(url_for("index"))  # or "generate" or any other page
        else:
            return "Invalid credentials. Please try again."

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        password_hash = generate_password_hash(password)

        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                               (name, email, password_hash))
                conn.commit()
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            return "Email already registered. Please log in."

    return render_template("signup.html")


@app.route("/")
def index():
    return render_template('index.html')

@app.route("/generate", methods=["GET", "POST"])
def generate():
    pages, images = [], []
    field = ""
    topic = ""
    grade = ""
    title = ""
    subtitle =""

    # if os.path.exists(STORY_JSON_PATH) and os.path.exists(IMAGES_JSON_PATH):
    #     with open(STORY_JSON_PATH) as f:
    #         pages = json.load(f)
    #     with open(IMAGES_JSON_PATH) as f:
    #         images = json.load(f)
    if request.method == "POST":
        field = request.form["field"]
        topic = request.form["topic"]
        grade = request.form["grade"]
        age = request.form["age"]
        gender = request.form["gender"]

        prompt = (
            f"Write a creative children's storybook for a {gender} student in grade {grade} (age {age}) "
            f"about '{topic}' in the field of {field}. Make it fun, educational, and age-appropriate."
        )
        print("Prompt:",prompt)

        try:
            job_id = "ftjob-TheurePsrJNBqE8WFRwbkSc7"
            job_info = client.fine_tuning.jobs.retrieve(job_id)
            ourmodel = job_info.fine_tuned_model
            print("Start Generating......")
            response = client.chat.completions.create(
                model= ourmodel,
                messages=[
                    {"role": "system", "content": "You are a friendly AI that tells helpful, age-appropriate stories to children."},
                    {"role": "user", "content": prompt}
                ]
            )
            story = response.choices[0].message.content
            print(story)
            pages = split_story_into_pages(story)
            print(pages)
            # ["content for page1", "content for page2", "content for page3"]

            story_id = str(uuid.uuid4())[:8]
            # images = generate_images_for_pages(pages, story_id)

            # Save for reuse
            with open(STORY_JSON_PATH, "w") as f:
                json.dump(pages, f)
            # with open(IMAGES_JSON_PATH, "w") as f:
            #     json.dump(images, f)

        except Exception as e:
            pages = [f"Error generating story: {e}"]
            # images = ["/static/images/default.jpg"]

    return render_template("generate.html", pages=pages, images=images, field=field, topic=topic, grade=grade, title=title, subtitle=subtitle)

if __name__ == "__main__":
    app.run(debug=True)
