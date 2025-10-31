from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo          # para hora local MX
from supabase import create_client, Client
import fitz                            # PyMuPDF
import os

app = Flask(__name__)
app.secret_key = 'clave_muy_segura_123456'

# Supabase
SUPABASE_URL = "https://xsagwqepoljfsogusubw.supabase.co"
SUPABASE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhzYWd3cWVwb2xqZnNvZ3VzdWJ3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM5NjM3NTUs"
    "ImV4cCI6MjA1OTUzOTc1NX0.NUixULn0m2o49At8j6X58UqbXre2O2_JStqzls_8Gws"
)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ENTIDAD FIJA PARA GUANAJUATO
ENTIDAD = "guanajuato"

# Asegura carpeta para PDFs
os.makedirs("static/pdfs", exist_ok=True)

# ----------------------------------------------------------------------
# Función para generar PDF usando plantilla guanajuato.pdf
# ----------------------------------------------------------------------
def generar_pdf(folio: str, numero_serie: str) -> bool:
    try:
        plantilla = "guanajuato.pdf"
        fecha_texto = datetime.now(tz=ZoneInfo("America/Mexico_City")).strftime("%d/%m/%Y")
        ruta_pdf = f"static/pdfs/{folio}.pdf"
        doc = fitz.open(plantilla)
        page = doc[0]
        # Inserta datos en plantilla
        page.insert_text((255.0, 180.0), numero_serie, fontsize=10, fontname="helv")
        page.insert_text((255.0, 396.0), fecha_texto, fontsize=10, fontname="helv")
        doc.save(ruta_pdf)
        doc.close()
        return True
    except Exception as e:
        print(f"ERROR al generar PDF: {e}")
        return False

# ----------------------------------------------------------------------
# RUTAS
# ----------------------------------------------------------------------
@app.route('/')
def inicio():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # Admin hardcodeado
        if username == 'Serg890105tm3' and password == 'Serg890105tm3':
            session['admin'] = True
            return redirect(url_for('admin'))
        # Usuario Supabase
        res = supabase.table("verificaciondigitalcdmx") \
                      .select("*") \
                      .eq("username", username) \
                      .eq("password", password).execute()
        if res.data:
            session['user_id'] = res.data[0]['id']
            session['username'] = username
            return redirect(url_for('registro_usuario'))
        
        return render_template('bloqueado.html')
    return render_template('login.html')
    
@app.route('/admin')
def admin():
    if 'admin' not in session:
        return redirect(url_for('login'))
    return render_template('panel.html')

@app.route('/crear_usuario', methods=['GET', 'POST'])
def crear_usuario():
    if 'admin' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        u = request.form['username']
        p = request.form['password']
        fol = int(request.form['folios'])
        exists = supabase.table("verificaciondigitalcdmx") \
                         .select("id").eq("username", u).execute()
        if exists.data:
            flash("Error: el usuario ya existe.", 'error')
        else:
            supabase.table("verificaciondigitalcdmx").insert({
                "username": u,
                "password": p,
                "folios_asignac": fol,
                "folios_usados": 0
            }).execute()
            flash("Usuario creado exitosamente.", 'success')
    return render_template('crear_usuario.html')

@app.route('/registro_usuario', methods=['GET', 'POST'])
def registro_usuario():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    uid = session['user_id']
    if request.method == 'POST':
        folio    = request.form['folio']
        marca    = request.form['marca']
        linea    = request.form['linea']
        anio     = request.form['anio']
        serie    = request.form['serie']
        motor    = request.form['motor']
        telefono = request.form.get('telefono', '')
        vigencia = int(request.form['vigencia'])
        # Verifica duplicado
        if supabase.table("folios_registrados").select("folio") \
                   .eq("folio", folio).execute().data:
            flash('Error: folio ya existe.', 'error')
            return redirect(url_for('registro_usuario'))
        # Verifica folios disponibles
        ud = supabase.table("verificaciondigitalcdmx") \
                     .select("folios_asignac,folios_usados") \
                     .eq("id", uid).execute().data[0]
        if ud['folios_asignac'] - ud['folios_usados'] < 1:
            flash('Sin folios disponibles.', 'error')
            return redirect(url_for('registro_usuario'))
        # Crea registro
        ahora = datetime.now()
        supabase.table("folios_registrados").insert({
            "folio": folio,
            "marca": marca,
            "linea": linea,
            "anio": anio,
            "numero_serie": serie,
            "numero_motor": motor,
            "fecha_expedicion": ahora.isoformat(),
            "fecha_vencimiento": (ahora + timedelta(days=vigencia)).isoformat(),
            "entidad": ENTIDAD,
            "numero_telefono": telefono
        }).execute()
        supabase.table("verificaciondigitalcdmx").update({
            "folios_usados": ud['folios_usados'] + 1
        }).eq("id", uid).execute()
        # Genera PDF
        generar_pdf(folio, serie)
        return render_template('exitoso.html',
                               folio=folio,
                               enlace_pdf=url_for('descargar_pdf', folio=folio))
    # GET → muestra formulario
    info = supabase.table("verificaciondigitalcdmx") \
                  .select("folios_asignac,folios_usados") \
                  .eq("id", uid).execute().data[0]
    return render_template('registro_usuario.html', folios_info=info)

@app.route('/registro_admin', methods=['GET', 'POST'])
def registro_admin():
    if 'admin' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        folio    = request.form['folio']
        marca    = request.form['marca']
        linea    = request.form['linea']
        anio     = request.form['anio']
        serie    = request.form['serie']
        motor    = request.form['motor']
        telefono = request.form.get('telefono', '')
        vigencia = int(request.form['vigencia'])
        # Verifica duplicado
        if supabase.table("folios_registrados").select("folio") \
                   .eq("folio", folio).execute().data:
            flash('Error: folio ya existe.', 'error')
            return render_template('registro_admin.html')
        ahora = datetime.now()
        supabase.table("folios_registrados").insert({
            "folio": folio,
            "marca": marca,
            "linea": linea,
            "anio": anio,
            "numero_serie": serie,
            "numero_motor": motor,
            "fecha_expedicion": ahora.isoformat(),
            "fecha_vencimiento": (ahora + timedelta(days=vigencia)).isoformat(),
            "entidad": ENTIDAD,
            "numero_telefono": telefono
        }).execute()
        generar_pdf(folio, serie)
        return render_template('exitoso.html',
                               folio=folio,
                               enlace_pdf=url_for('descargar_pdf', folio=folio))
    return render_template('registro_admin.html')

@app.route('/consulta_folio', methods=['GET', 'POST'])
def consulta_folio():
    resultado = None
    if request.method == 'POST':
        folio = request.form['folio'].strip().upper()
        row   = supabase.table("folios_registrados") \
                        .select("*").eq("folio", folio).execute().data
        if not row:
            resultado = {"estado": "No encontrado", "folio": folio}
        else:
            r  = row[0]
            fe = datetime.fromisoformat(r['fecha_expedicion'])
            fv = datetime.fromisoformat(r['fecha_vencimiento'])
            estado = "VIGENTE" if datetime.now() <= fv else "VENCIDO"
            resultado = {
                "estado": estado,
                "folio": folio,
                "fecha_expedicion": fe.strftime("%d/%m/%Y"),
                "fecha_vencimiento": fv.strftime("%d/%m/%Y"),
                "marca": r['marca'],
                "linea": r['linea'],
                "año": r['anio'],
                "numero_serie": r['numero_serie'],
                "numero_motor": r['numero_motor'],
                "entidad": r.get('entidad',''),
                "telefono": r.get('numero_telefono','')
            }
        return render_template('resultado_consulta.html', resultado=resultado)
    return render_template('consulta_folio.html')

@app.route('/consulta/<folio>')
def consulta_directa(folio):
    """Ruta para QR dinámico - busca automáticamente el folio"""
    folio = folio.strip().upper()
    row = supabase.table("folios_registrados") \
                  .select("*").eq("folio", folio).execute().data
    
    if not row:
        resultado = {"estado": "No encontrado", "folio": folio}
    else:
        r = row[0]
        fe = datetime.fromisoformat(r['fecha_expedicion'])
        fv = datetime.fromisoformat(r['fecha_vencimiento'])
        estado = "VIGENTE" if datetime.now() <= fv else "VENCIDO"
        resultado = {
            "estado": estado,
            "folio": folio,
            "fecha_expedicion": fe.strftime("%d/%m/%Y"),
            "fecha_vencimiento": fv.strftime("%d/%m/%Y"),
            "marca": r['marca'],
            "linea": r['linea'],
            "año": r['anio'],
            "numero_serie": r['numero_serie'],
            "numero_motor": r['numero_motor'],
            "entidad": r.get('entidad',''),
            "telefono": r.get('numero_telefono','')
        }
    
    return render_template('resultado_consulta.html', resultado=resultado)

@app.route('/admin_folios')
def admin_folios():
    if 'admin' not in session:
        return redirect(url_for('login'))
    folios = supabase.table("folios_registrados") \
                    .select("*").execute().data or []
    ahora = datetime.now()
    for f in folios:
        fv = datetime.fromisoformat(f['fecha_vencimiento'])
        f['estado'] = "VIGENTE" if ahora <= fv else "VENCIDO"
    return render_template('admin_folios.html', folios=folios)

@app.route('/editar_folio/<folio>', methods=['GET', 'POST'])
def editar_folio(folio):
    if 'admin' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        data = {key: request.form[key] for key in [
            'marca','linea','anio','numero_serie','numero_motor',
            'entidad','numero_telefono','fecha_expedicion','fecha_vencimiento'
        ]}
        supabase.table("folios_registrados").update(data).eq("folio", folio).execute()
        flash("Folio actualizado.", "success")
        return redirect(url_for('admin_folios'))
    row = supabase.table("folios_registrados") \
                  .select("*").eq("folio", folio).execute().data
    if not row:
        flash("Folio no encontrado.", "error")
        return redirect(url_for('admin_folios'))
    return render_template('editar_folio.html', folio=row[0])

@app.route('/eliminar_folio', methods=['POST'])
def eliminar_folio():
    if 'admin' not in session:
        return redirect(url_for('login'))
    folio = request.form['folio']
    supabase.table("folios_registrados").delete().eq("folio", folio).execute()
    flash("Folio eliminado.", "success")
    return redirect(url_for('admin_folios'))

@app.route('/descargar_pdf/<folio>')
def descargar_pdf(folio):
    path = f"static/pdfs/{folio}.pdf"
    return send_file(path, as_attachment=True)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
