"""
SolarIQ Server - lokalno i cloud
"""
import os
import sys
import glob
import base64
import threading
import subprocess
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

BAZA_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BAZA_DIR)
PODACI_DIR = os.path.join(DATA_DIR, "hep_podaci")
FS_PODACI_DIR = os.path.join(DATA_DIR, "fs_podaci")

app = Flask(__name__, static_folder=BAZA_DIR)
CORS(app)

sync_status = {"running": False, "poruka": "Čeka se sinkronizacija", "ok": None}

def citaj_fajlove(folder):
    podaci = []
    for putanja in sorted(glob.glob(os.path.join(folder, "*.xlsx")) + glob.glob(os.path.join(folder, "*.xls"))):
        naziv = os.path.basename(putanja)
        with open(putanja, 'rb') as f:
            sadrzaj = base64.b64encode(f.read()).decode()
        podaci.append({"naziv": naziv, "sadrzaj": sadrzaj})
    return podaci

def parse_fs_files():
    import openpyxl
    rezultati = {}
    if not os.path.exists(FS_PODACI_DIR):
        return rezultati
    for putanja in sorted(glob.glob(os.path.join(FS_PODACI_DIR, "*.xlsx"))):
        try:
            wb = openpyxl.load_workbook(putanja, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            header_row = -1
            for i, row in enumerate(rows):
                if row[0] and 'Statistical Period' in str(row[0]):
                    header_row = i
                    break
            if header_row < 0:
                continue
            headers = [str(h or '').strip() for h in rows[header_row]]
            def find_col(name):
                for i, h in enumerate(headers):
                    if name in h:
                        return i
                return -1
            col_pv = find_col('PV Yield')
            col_export = find_col('Export (kWh)')
            col_import = find_col('Import (kWh)')
            col_self = -1
            for i, h in enumerate(headers):
                if 'Self-consumption' in h and 'kWh' in h and '%' not in h:
                    col_self = i
                    break
            col_cons = find_col('Consumption (kWh)')
            col_peak = find_col('Peak Power')
            col_co2 = find_col('CO')
            by_month = {}
            for row in rows[header_row+1:]:
                period = str(row[0] or '').strip()
                if not period or len(period) < 8:
                    continue
                parts = period.split('-')
                if len(parts) < 3:
                    continue
                ym = f"{parts[0]}-{parts[1]}"
                if ym not in by_month:
                    by_month[ym] = {'pvYield':0,'export':0,'import':0,'selfCons':0,'consumption':0,'peak':0,'co2':0,'days':0,'daily':{}}
                def val(c):
                    return float(row[c] or 0) if c >= 0 and row[c] not in (None, '') else 0
                by_month[ym]['pvYield'] += val(col_pv)
                by_month[ym]['export'] += val(col_export)
                by_month[ym]['import'] += val(col_import)
                by_month[ym]['selfCons'] += val(col_self)
                by_month[ym]['consumption'] += val(col_cons)
                by_month[ym]['co2'] += val(col_co2)
                pv_day = val(col_pv)
                pk = val(col_peak)
                if pk > by_month[ym]['peak']:
                    by_month[ym]['peak'] = pk
                # Spremi dnevne podatke
                direct_day = val(col_self) if col_self >= 0 else max(0, pv_day - val(col_export))
                by_month[ym]['daily'][period] = {
                    'pv': round(pv_day, 3),
                    'export': round(val(col_export), 3),
                    'import': round(val(col_import), 3),
                    'direct': round(direct_day, 3),
                    'consumption': round(val(col_cons), 3),
                    'peak': round(pk, 3)
                }
                by_month[ym]['days'] += 1
            for ym, d in by_month.items():
                direct = d['selfCons'] if d['selfCons'] > 0 else max(0, d['pvYield'] - d['export'])
                rezultati[ym] = {
                    'productionTotal': round(d['pvYield'], 2),
                    'directConsumption': round(direct, 2),
                    'gridFeed': round(d['export'], 2),
                    'gridImport': round(d['import'], 2),
                    'selfConsumptionRate': round(direct/d['pvYield']*100, 2) if d['pvYield'] > 0 else 0,
                    'consumption': round(d['consumption'], 2),
                    'peakPower': round(d['peak'], 2),
                    'co2': round(d['co2'], 4),
                    'days': d['days'],
                    'daily': d['daily'],
                    'source': 'xlsx'
                }
        except Exception as e:
            print(f"Greška parsiranja {putanja}: {e}")
    return rezultati

def run_sync_background(source, username, password):
    global sync_status
    sync_status["running"] = True
    sync_status["ok"] = None
    try:
        script = "hep_sync.py" if source == "hep" else "fs_sync.py"
        script_path = os.path.join(BAZA_DIR, script)
        sync_status["poruka"] = f"Pokrećem {script}..."
        proc = subprocess.Popen(
            [sys.executable, '-u', script_path, username, password],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=BAZA_DIR, bufsize=1
        )
        for line in proc.stdout:
            line = line.rstrip()
            print(f"[sync] {line}", flush=True)
            sync_status["poruka"] = line
        proc.wait(timeout=300)
        if proc.returncode == 0:
            sync_status["ok"] = True
            sync_status["poruka"] = f"✅ {source.upper()} sinkronizacija uspješna!"
        else:
            sync_status["ok"] = False
            sync_status["poruka"] = f"❌ Greška pri sinkronizaciji"
    except Exception as e:
        sync_status["ok"] = False
        sync_status["poruka"] = f"❌ {str(e)}"
    finally:
        sync_status["running"] = False

@app.route('/')
def index():
    return send_from_directory(BAZA_DIR, 'index.html')

@app.route('/api/sync', methods=['POST'])
def api_sync():
    return jsonify({"ok": True, "novi": [], "poruka": "Podaci su ažurni"})

@app.route('/api/podaci')
def api_podaci():
    try:
        return jsonify({"ok": True, "fajlovi": citaj_fajlove(PODACI_DIR), "ukupno": len(os.listdir(PODACI_DIR)) if os.path.exists(PODACI_DIR) else 0})
    except Exception as e:
        return jsonify({"ok": False, "greska": str(e)}), 500

@app.route('/api/fs-podaci')
def api_fs_podaci():
    try:
        fajlovi = citaj_fajlove(FS_PODACI_DIR) if os.path.exists(FS_PODACI_DIR) else []
        return jsonify({"ok": True, "fajlovi": fajlovi, "ukupno": len(fajlovi)})
    except Exception as e:
        return jsonify({"ok": False, "greska": str(e)}), 500

@app.route('/api/fs-parsed')
def api_fs_parsed():
    try:
        return jsonify({"ok": True, "podaci": parse_fs_files()})
    except Exception as e:
        return jsonify({"ok": False, "greska": str(e)}), 500

@app.route('/api/sync_custom', methods=['POST'])
def api_sync_custom():
    global sync_status
    if sync_status["running"]:
        return jsonify({"ok": False, "poruka": "Sinkronizacija već u tijeku..."})
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    source = data.get('source', 'hep')
    if not username or not password:
        return jsonify({"ok": False, "poruka": "Nedostaju podaci za prijavu."})
    thread = threading.Thread(target=run_sync_background, args=(source, username, password))
    thread.daemon = True
    thread.start()
    return jsonify({"ok": True, "poruka": "Sinkronizacija pokrenuta..."})

@app.route('/api/sync_status')
def api_sync_status():
    return jsonify(sync_status)

@app.route('/api/status')
def api_status():
    hep = [os.path.basename(f) for f in sorted(glob.glob(os.path.join(PODACI_DIR, "*.xlsx")) + glob.glob(os.path.join(PODACI_DIR, "*.xls")))]
    fs = [os.path.basename(f) for f in sorted(glob.glob(os.path.join(FS_PODACI_DIR, "*.xlsx")))]
    return jsonify({"ok": True, "hep": hep, "fs": fs})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print("=" * 50)
    print(f"SolarIQ Server pokrenut!")
    print(f"Otvori: http://localhost:{port}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)
