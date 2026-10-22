import os
import pymysql
from flask import Flask, render_template, request
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

def get_connection():
    conn = pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "dukon"),
        cursorclass=pymysql.cursors.DictCursor
    )
    return conn


@app.route('/', methods=['GET', 'POST'])
def index():
    error = None
    message = None

    conn = get_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        ism = request.form.get('ism', '').strip()
        familiya = request.form.get('familiya', '').strip()
        tulov_usuli = request.form.get('tulov_usuli')

        mahsulot_ids = request.form.getlist('mahsulot_id')
        miqdorlar_str = request.form.getlist('miqdor')

        items = []
        if not ism or not familiya:
            error = "Xaridorning ism va familiyasi kiritilishi shart."
        else:
            for mid, m_str in zip(mahsulot_ids, miqdorlar_str):
                mid = (mid or "").strip()
                m_str = (m_str or "").strip()
                if not mid and not m_str:
                    continue
                if not mid or not m_str:
                    error = "Har bir tanlangan mahsulot uchun miqdor ham kiritilishi kerak."
                    break
                try:
                    qty = int(m_str)
                except (TypeError, ValueError):
                    error = "Miqdor faqat butun son bo'lishi kerak."
                    break
                if qty <= 0:
                    error = "Miqdor 0 dan katta bo'lishi kerak."
                    break
                items.append((mid, qty))

            if not items and not error:
                error = "Hech bo'lmaganda bitta mahsulot tanlang."

        if not error:
            try:
                conn.autocommit = False

                cursor.execute("""
                    SELECT xaridor_id, tashrif_buyurishlar_soni
                    FROM xaridor
                    WHERE ism = %s AND familiya = %s
                    LIMIT 1
                """, (ism, familiya))
                xaridor = cursor.fetchone()

                if xaridor:
                    xaridor_id = xaridor['xaridor_id']
                    cursor.execute("""
                        UPDATE xaridor
                        SET tashrif_buyurishlar_soni = tashrif_buyurishlar_soni + 1
                        WHERE xaridor_id = %s
                    """, (xaridor_id,))
                else:
                    cursor.execute("""
                        INSERT INTO xaridor (ism, familiya, tashrif_buyurishlar_soni)
                        VALUES (%s, %s, %s)
                    """, (ism, familiya, 1))
                    xaridor_id = cursor.lastrowid

                for mid, qty in items:
                    cursor.execute("""
                        SELECT jami_keltirilgan_miqdori
                        FROM mahsulot
                        WHERE mahsulot_id = %s
                        FOR UPDATE
                    """, (mid,))
                    mahsulot = cursor.fetchone()

                    if not mahsulot:
                        error = f"ID={mid} bo'lgan mahsulot topilmadi."
                        break
                    if mahsulot['jami_keltirilgan_miqdori'] < qty:
                        error = f"ID={mid} bo'lgan mahsulot uchun omborda yetarli miqdor yo'q."
                        break

                if error:
                    conn.rollback()
                else:
                    for mid, qty in items:
                        cursor.execute("""
                            INSERT INTO sotuv (sanasi, tulov_usuli, olingan_miqdor, mahsulot_id, xaridor_id)
                            VALUES (NOW(), %s, %s, %s, %s)
                        """, (tulov_usuli, qty, mid, xaridor_id))

                        cursor.execute("""
                            UPDATE mahsulot
                            SET jami_keltirilgan_miqdori = jami_keltirilgan_miqdori - %s
                            WHERE mahsulot_id = %s
                        """, (qty, mid))

                    conn.commit()
                    message = "Barcha sotuvlar muvaffaqiyatli saqlandi."

            except Exception as e:
                conn.rollback()
                print("Xatolik:", e)
                error = "Ma'lumotlar bazasida xatolik yuz berdi."
            finally:
                conn.autocommit = True

    cursor.execute("""
        SELECT mahsulot_id, nomi, jami_keltirilgan_miqdori, narxi
        FROM mahsulot
        ORDER BY nomi
    """)
    mahsulotlar = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'index.html',
        mahsulotlar=mahsulotlar,
        error=error,
        message=message
    )


@app.route('/mahsulotlar')
def mahsulotlar():
    sort = request.args.get('sort', 'id_asc')

    if sort == 'kategoriya':
        order_by = "kategoriya ASC, mahsulot_id ASC"
    elif sort == 'narx_asc':
        order_by = "narxi ASC"
    elif sort == 'narx_desc':
        order_by = "narxi DESC"
    elif sort == 'muddati_asc':
        order_by = "muddati ASC"
    elif sort == 'muddati_desc':
        order_by = "muddati DESC"
    else:
        sort = 'id_asc'
        order_by = "mahsulot_id ASC"

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT mahsulot_id, kategoriya, nomi, jami_keltirilgan_miqdori, muddati, narxi
        FROM mahsulot
        ORDER BY {order_by}
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('mahsulotlar.html', mahsulotlar=rows, sort=sort)


@app.route('/xaridorlar')
def xaridorlar():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT xaridor_id, ism, familiya, tashrif_buyurishlar_soni
        FROM xaridor
        ORDER BY xaridor_id
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('xaridorlar.html', xaridorlar=rows)


@app.route('/sotuvlar')
def sotuvlar():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            s.sotuv_id,
            s.sanasi,
            s.tulov_usuli,
            s.olingan_miqdor,
            m.nomi AS mahsulot_nomi,
            x.ism AS xaridor_ismi,
            x.familiya AS xaridor_familiyasi
        FROM sotuv s
        JOIN mahsulot m ON s.mahsulot_id = m.mahsulot_id
        JOIN xaridor x ON s.xaridor_id = x.xaridor_id
        ORDER BY s.sotuv_id
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('sotuvlar.html', sotuvlar=rows)

if __name__ == '__main__':
    app.run(debug=True)

# sefawffwafawfefse
