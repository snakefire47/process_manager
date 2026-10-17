import RPi.GPIO as GPIO
import time
import threading
import sqlite3
from io import BytesIO
from contextlib import closing
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, send_file
import json
import os
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

app = Flask(__name__)
GPIO.setmode(GPIO.BCM)

BLINK_PIN = 18

GPIO.setup(
	BLINK_PIN,
	GPIO.OUT,
	initial=GPIO.HIGH
)


# ----------------------------------
# Helper Functions
# ----------------------------------

def recipe_file(process_name):

    filename = process_name.replace(" ", "_")
    filename = filename.replace("ó", "o")
    filename = filename.replace("á", "a")
    filename = filename.replace("é", "e")
    filename = filename.replace("í", "i")
    filename = filename.replace("ú", "u")

    return f"recipes/{filename}.json"


def load_processes():

    path = "recipes/processes.json"

    if not os.path.exists(path):

        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_processes(processes):

    with open(
        "recipes/processes.json",
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            processes,
            f,
            indent=4,
            ensure_ascii=False
        )


def tpm_database_path():

    os.makedirs(app.instance_path, exist_ok=True)
    path = os.path.join(app.instance_path, "tpm_reports.sqlite3")

    with closing(sqlite3.connect(path)) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS tpm_reports (
                report_number INTEGER PRIMARY KEY AUTOINCREMENT,
                machine TEXT NOT NULL,
                report_date TEXT NOT NULL,
                report_time TEXT NOT NULL,
                ok_count INTEGER NOT NULL,
                not_ok_count INTEGER NOT NULL,
                responses_json TEXT NOT NULL,
                maintenance_order TEXT NOT NULL DEFAULT ''
            )
        """)
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(tpm_reports)")
        }
        if "maintenance_order" not in columns:
            connection.execute("""
                ALTER TABLE tpm_reports
                ADD COLUMN maintenance_order TEXT NOT NULL DEFAULT ''
            """)
        connection.commit()

    return path


# ----------------------------------
# Home
# ----------------------------------

@app.route("/")
def home():
    return render_template("index.html")


# ----------------------------------
# Process Guide
# ----------------------------------

@app.route("/process")
def process():

    processes = load_processes()

    return render_template(
        "process.html",
        processes=processes
    )


# ----------------------------------
# Add Process
# ----------------------------------

@app.route("/add-process", methods=["POST"])
def add_process():

    name = request.form["process_name"].strip()

    if not name:
        return redirect("/process")

    processes = load_processes()

    if name not in processes:

        processes.append(name)

        save_processes(processes)

        filepath = recipe_file(name)

        recipe = {
            "process": name,
            "steps": []
        }

        with open(filepath, "w", encoding="utf-8") as f:

            json.dump(
                recipe,
                f,
                indent=4,
                ensure_ascii=False
            )

    return redirect("/process")


# ----------------------------------
# Delete Process
# ----------------------------------

@app.route("/delete-process", methods=["POST"])
def delete_process():

    process_name = request.form["process_name"]

    processes = load_processes()

    if process_name in processes:

        processes.remove(process_name)

        save_processes(processes)

        filepath = recipe_file(process_name)

        if os.path.exists(filepath):
            os.remove(filepath)

    return redirect("/process")


# ----------------------------------
# Recipe Editor
# ----------------------------------
@app.route("/recipe-editor", methods=["GET", "POST"])
def recipe_editor():

    process = request.args.get(
        "process",
        "Aceleración F585"
    )

    filepath = recipe_file(process)

    if os.path.exists(filepath):

        with open(filepath, "r", encoding="utf-8") as f:
            recipe = json.load(f)

    else:

        recipe = {
            "process": process,
            "steps": []
        }

    if request.method == "POST":

        titles = request.form.getlist("title")
        times = request.form.getlist("time")

        steps = []

        for i in range(len(titles)):

            # Keep existing media by default
            media_filename = ""

            if i < len(recipe["steps"]):
                media_filename = recipe["steps"][i].get(
                    "media",
                    ""
                )

            # Check if a new file was uploaded
            media_key = f"media{i}"

            if media_key in request.files:

                file = request.files[media_key]

                if file and file.filename:

                    media_filename = secure_filename(
                        file.filename
                    )

                    file.save(
                        os.path.join(
                            "static/media",
                            media_filename
                        )
                    )

            steps.append({
                "title": titles[i],
                "time": int(times[i]),
                "media": media_filename
            })

        recipe["steps"] = steps

        with open(filepath, "w", encoding="utf-8") as f:

            json.dump(
                recipe,
                f,
                indent=4,
                ensure_ascii=False
            )

        return redirect(
            f"/recipe-editor?process={process}"
        )

    return render_template(
        "recipe_editor.html",
        process=process,
        recipe=recipe
    )

# ----------------------------------
# Player
# ----------------------------------

@app.route("/player")
def player():

    process = request.args.get("process")

    filepath = recipe_file(process)

    if not os.path.exists(filepath):
        return redirect("/process")

    with open(filepath, "r", encoding="utf-8") as f:
        recipe = json.load(f)

    return render_template(
        "player.html",
        recipe=recipe
    )

# ----------------------------------
# Blink
# ----------------------------------
def blink_led():

    for _ in range(1):

        GPIO.output(
            BLINK_PIN,
            GPIO.LOW
        )

        time.sleep(0.7)

        GPIO.output(
            BLINK_PIN,
            GPIO.HIGH
        )

        time.sleep(0.2)
@app.route("/blink-step")
def blink_step():

    threading.Thread(
        target=blink_led
    ).start()

    return "OK"

@app.route("/process-complete")
def process_complete():

    GPIO.output(BLINK_PIN, GPIO.LOW)
    time.sleep(1)
    GPIO.output(BLINK_PIN, GPIO.HIGH)

    return "OK"


# ----------------------------------
# TPM
# ----------------------------------

@app.route("/tpm")
def tpm():
    with closing(sqlite3.connect(tpm_database_path())) as connection:
        latest_report = connection.execute("""
            SELECT report_date, report_time
            FROM tpm_reports
            ORDER BY report_number DESC
            LIMIT 1
        """).fetchone()

    return render_template("tpm.html", latest_report=latest_report)


@app.route("/tpm-molino-2", methods=["GET", "POST"])
def tpm_molino_2():
    item_names = [f"item_{number}" for number in range(1, 14)]

    if request.method == "POST":
        responses = {
            name: request.form.get(name, "")
            for name in item_names
        }
        allowed_responses = {"OK", "Not OK"}

        if any(response not in allowed_responses for response in responses.values()):
            return render_template(
                "tpm_molino_2.html",
                selected_statuses=responses,
                form_error="Selecciona OK o Not OK para cada punto antes de enviar."
            ), 400

        ok_count = sum(response == "OK" for response in responses.values())
        not_ok_count = sum(response == "Not OK" for response in responses.values())
        now = datetime.now()

        with closing(sqlite3.connect(tpm_database_path())) as connection:
            cursor = connection.execute("""
                INSERT INTO tpm_reports (
                    machine, report_date, report_time, ok_count, not_ok_count, responses_json
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                "Molino 2",
                now.strftime("%d/%m/%Y"),
                now.strftime("%H:%M"),
                ok_count,
                not_ok_count,
                json.dumps(responses, ensure_ascii=False)
            ))
            report_number = cursor.lastrowid
            connection.commit()

        if not_ok_count:
            return render_template(
                "tpm_maintenance_order.html",
                report_number=report_number
            )

        return redirect("/tpm")

    return render_template("tpm_molino_2.html", selected_statuses={})


@app.route("/tpm/maintenance-order", methods=["POST"])
def save_tpm_maintenance_order():
    report_number = request.form.get("report_number", "")
    maintenance_order = request.form.get("maintenance_order", "").strip()

    if not report_number.isdigit() or len(maintenance_order) > 120:
        return redirect("/tpm")

    with closing(sqlite3.connect(tpm_database_path())) as connection:
        connection.execute("""
            UPDATE tpm_reports
            SET maintenance_order = ?
            WHERE report_number = ? AND not_ok_count > 0
        """, (maintenance_order, int(report_number)))
        connection.commit()

    return redirect("/tpm")


@app.route("/tpm/reports")
def tpm_reports():
    with closing(sqlite3.connect(tpm_database_path())) as connection:
        reports = connection.execute("""
            SELECT report_number, machine, report_date, report_time, ok_count, not_ok_count
            FROM tpm_reports
            ORDER BY report_number DESC
        """).fetchall()

    return render_template("tpm_reports.html", reports=reports)


@app.route("/tpm/download-report")
def download_tpm_report():
    with closing(sqlite3.connect(tpm_database_path())) as connection:
        reports = connection.execute("""
            SELECT report_number, machine, report_date, report_time,
                   ok_count, not_ok_count, responses_json, maintenance_order
            FROM tpm_reports
            ORDER BY report_number
        """).fetchall()

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "TPM Reports"

    headers = [
        "N. reporte", "TPM", "Fecha", "Hora", "Resp. OK", "Resp. NOK",
        *(f"R{number}" for number in range(1, 14)), "Orden de mantenimiento"
    ]
    worksheet.append(headers)

    header_fill = PatternFill("solid", fgColor="B4C7E7")
    ok_fill = PatternFill("solid", fgColor="E2F0D9")
    not_ok_fill = PatternFill("solid", fgColor="F4CCCC")
    thin_gray = Side(style="thin", color="D9E1F2")
    cell_border = Border(
        left=thin_gray,
        right=thin_gray,
        top=thin_gray,
        bottom=thin_gray
    )

    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="left")
        cell.border = cell_border

    for report in reports:
        responses = json.loads(report[6])
        row = [
            report[0],
            report[1],
            datetime.strptime(report[2], "%d/%m/%Y").date(),
            datetime.strptime(report[3], "%H:%M").time(),
            report[4],
            report[5],
            *[
                "ok" if responses.get(f"item_{number}") == "OK" else "nok"
                for number in range(1, 14)
            ],
            report[7]
        ]
        worksheet.append(row)
        current_row = worksheet.max_row
        row_fill = not_ok_fill if report[5] > 0 else ok_fill

        for cell in worksheet[current_row]:
            cell.fill = row_fill
            cell.border = cell_border
            cell.alignment = Alignment(vertical="center")

        worksheet.cell(current_row, 1).number_format = "0000"
        worksheet.cell(current_row, 3).number_format = "DD/MM/YYYY"
        worksheet.cell(current_row, 4).number_format = "HH:MM"
        for column in range(5, 21):
            worksheet.cell(current_row, column).alignment = Alignment(
                horizontal="center",
                vertical="center"
            )

    column_widths = [14, 16, 14, 10, 12, 12] + [8] * 13 + [30]
    for column_number, width in enumerate(column_widths, start=1):
        worksheet.column_dimensions[
            worksheet.cell(row=1, column=column_number).column_letter
        ].width = width

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="tpm_reports.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ----------------------------------
# Settings
# ----------------------------------

@app.route("/settings")
def settings():
    return render_template("settings.html")


# ----------------------------------
# Run
# ----------------------------------

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5004,
        debug=True
    )
