from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime, timedelta
from supabase import create_client, Client
import fitz
import os

app = Flask(__name__)
app.secret_key = 'clave_muy_segura_123456'

SUPABASE_URL = "https://xsagwqepoljfsogusubw.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhzYWd3cWVwb2xqZnNvZ3VzdWJ3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM5NjM3NTUsImV4cCI6MjA1OTUzOTc1NX0.NUixULn0m2o49At8j6X58UqbXre2O2_JStqzls_8Gws"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/')
def inicio():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contrasena = request.form['contrasena']
        if usuario == 'elwarrior' and contrasena == 'Warrior2025':
            session['admin'] = True
            return redirect(url_for('panel'))
        else:
            flash('Credenciales incorrectas', 'error')
    return render_template('login.html')

@app.route('/panel')
def panel():
    if 'admin' not in session:
        return redirect(url_for('login'))
    return render_template('panel.html')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if 'admin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        folio = request.form['folio']
        marca = request.form['marca']
        linea = request.form['linea']
        anio = request.form['anio']
        numero_serie = request.form['numero_serie']
        numero_motor = request.form['numero_motor']
        nombre = request.form['nombre']
        vigencia = int(request.form['vigencia'])

        existente = supabase.table("folios_registrados").select("*").eq("folio", folio).execute()
        if existente.data:
            flash("Error: el folio ya existe.", "error")
            return redirect(url_for('registro'))

        fecha_expedicion = datetime.now()
        fecha_vencimiento = fecha_expedicion + timedelta(days=vigencia)

        data = {
            "folio": folio,
            "marca": marca,
            "linea": linea,
            "anio": anio,
            "numero_serie": numero_serie,
            "numero_motor": numero_motor,
            "nombre": nombre,
            "vigencia": vigencia,
            "fecha_expedicion": fecha_expedicion.isoformat(),
            "fecha_vencimiento": fecha_vencimiento.isoformat()
        }

        supabase.table("folios_registrados").insert(data).execute()
        generar_pdf(folio, nombre, fecha_expedicion, fecha_vencimiento)
        return render_template("exitoso.html", folio=folio)

    return render_template('registro_admin.html')

def generar_pdf(folio, nombre, fecha_expedicion, fecha_vencimiento):
    try:
        os.makedirs("static/pdfs", exist_ok=True)
        plantilla = "static/recibo_permiso_guerrero_img.pdf"
        output_path = f"static/pdfs/{folio}.pdf"
        doc = fitz.open(plantilla)
        page = doc[0]

        page.insert_text((87, 662), folio, fontsize=12, color=(1, 0, 0))
        page.insert_text((147, 650), fecha_expedicion.strftime("%d/%m/%Y"), fontsize=12)
        page.insert_text((147, 630), fecha_vencimiento.strftime("%d/%m/%Y"), fontsize=12)
        page.insert_text((451, 326), nombre, fontsize=8)

        doc.save(output_path)
        doc.close()
    except Exception as e:
        print("Error al generar PDF:", e)

@app.route('/consulta', methods=['GET', 'POST'])
def consulta():
    resultado = None
    if request.method == 'POST':
        folio = request.form['folio']
        response = supabase.table("folios_registrados").select("*").eq("folio", folio).execute()
        registros = response.data

        if not registros:
            resultado = {"estado": "NO SE ENCUENTRA REGISTRADO", "folio": folio}
        else:
            r = registros[0]
            exp = datetime.fromisoformat(r['fecha_expedicion'])
            ven = datetime.fromisoformat(r['fecha_vencimiento'])
            hoy = datetime.now()
            estado = "VIGENTE" if hoy <= ven else "VENCIDO"

            resultado = {
                "estado": f"FOLIO {folio} : {estado}",
                "fecha_expedicion": exp.strftime("%d/%m/%Y"),
                "fecha_vencimiento": ven.strftime("%d/%m/%Y"),
                "marca": r['marca'],
                "linea": r['linea'],
                "anio": r['anio'],
                "numero_serie": r['numero_serie'],
                "numero_motor": r['numero_motor']
            }

        return render_template("resultado_consulta.html", resultado=resultado)

    return render_template("consulta_folio.html")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
