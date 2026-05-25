import streamlit as st
import json
import requests
import base64
import math
from bs4 import BeautifulSoup
from datetime import datetime, date
from supabase import create_client

st.set_page_config(
    page_title="TeeRadar",
    page_icon="favicon.png",
    layout="wide"
)

st.image("header.jpg", use_container_width=True)

# =========================
# CONFIGURACIÓN
# =========================

# Los datos funcionales se cargan desde Supabase.
# No se usan ficheros JSON para municipios, zonas, campos ni recorridos.

# =========================
# MODO DEBUG
# =========================

params = st.query_params
modo_debug = params.get("debug") == "1"

if "debug_payloads" not in st.session_state:
    st.session_state.debug_payloads = []

if "debug_responses" not in st.session_state:
    st.session_state.debug_responses = []

if "debug_filtros_distancias" not in st.session_state:
    st.session_state.debug_filtros_distancias = []

def registrar_debug(tipo, campo, recorrido, contenido):
    if not modo_debug:
        return

    entrada = {
        "campo": nombre_campo(campo) if campo else "Campo sin nombre",
        "recorrido": nombre_recorrido(recorrido) if recorrido else "Recorrido sin nombre",
        "contenido": contenido
    }

    if tipo == "payload":
        st.session_state.debug_payloads.append(entrada)
    elif tipo == "response":
        st.session_state.debug_responses.append(entrada)

def formatear_debug(lista):
    bloques = []

    for i, entrada in enumerate(lista, start=1):
        bloques.append(
            f"===== {i}. {entrada['campo']} | {entrada['recorrido']} =====\n"
            + json.dumps(entrada["contenido"], ensure_ascii=False, indent=2)
        )

    return "\n\n".join(bloques)

def pintar_caja_debug(titulo, lista):
    st.text_area(
        titulo,
        value=formatear_debug(lista),
        height=260,
        disabled=True
    )

def registrar_debug_filtro(campo, campo_activo="--", bounding_box="--",
                           recorrido_hoyos="--", haversine="--", matrix_ors="--",
                           origen="--", destino="--", resultado="Fuera de rango"):
    if not modo_debug:
        return

    st.session_state.debug_filtros_distancias.append({
        "Campo": nombre_campo(campo),
        "Campo activo": campo_activo,
        "Bounding Box": bounding_box,
        "Recorrido/hoyos": recorrido_hoyos,
        "Haversine": haversine,
        "Matrix ORS": matrix_ors,
        "Origen": origen,
        "Destino": destino,
        "Resultado": resultado
    })

def formatear_debug_filtros_distancias(lista):
    bloques = []

    for entrada in lista:
        bloques.append(
            f"Campo: {entrada['Campo']}\n"
            f"Campo activo: {entrada['Campo activo']}\n"
            f"Bounding Box: {entrada['Bounding Box']}\n"
            f"Recorrido/hoyos: {entrada['Recorrido/hoyos']}\n"
            f"Haversine: {entrada['Haversine']}\n"
            f"Matrix ORS: {entrada['Matrix ORS']}\n"
            f"Origen: {entrada['Origen']}\n"
            f"Destino: {entrada['Destino']}\n"
            f"Resultado: {entrada['Resultado']}"
        )

    return "\n\n".join(bloques)

def pintar_caja_debug_filtros_distancias(titulo, lista):
    st.text_area(
        titulo,
        value=formatear_debug_filtros_distancias(lista),
        height=360,
        disabled=True
    )

# =========================
# FUNCIONES
# =========================

def convertir_hora(hora_texto):
    return datetime.strptime(hora_texto, "%H:%M").time()

def obtener_valor_hidden(soup, id_campo):
    campo = soup.find("input", {"id": id_campo})
    return campo.get("value") if campo else None

def normalizar_bool(valor, defecto=False):
    """
    Convierte valores booleanos procedentes de Supabase o formularios a bool.
    """
    if valor is None:
        return defecto
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return valor.strip().lower() not in ("false", "0", "no", "n", "")
    return bool(valor)


def nombre_campo(campo):
    if not campo:
        return "Campo sin nombre"
    return campo.get("campo_ds") or "Campo sin nombre"


def nombre_recorrido(recorrido):
    if not recorrido:
        return "Recorrido sin nombre"
    return recorrido.get("recorrido_ds") or "Recorrido"


def get_campo_lat(campo):
    return campo.get("latitud")


def get_campo_lon(campo):
    return campo.get("longitud")


def obtener_metodos_activos(campo):
    """
    Devuelve los métodos activos asociados al campo.
    En la práctica ahora habrá normalmente uno, pero queda preparado
    para campos con más de un método de consulta.
    """
    return [
        metodo
        for metodo in campo.get("metodos", [])
        if normalizar_bool(metodo.get("activo_fl"), defecto=True)
    ]


def obtener_url_reserva(campo, metodo=None):
    return campo.get("url_reserva")


def es_campo_activo(campo):
    return normalizar_bool(campo.get("activo_fl"), defecto=True)


def mapear_recorrido_db(recorrido):
    """
    Recorrido procedente de Supabase.
    Mantiene solo nombres canónicos de BD.
    """
    return {
        "recorrido_id": recorrido.get("recorrido_id"),
        "campo_id": recorrido.get("campo_id"),
        "recorrido_ds": recorrido.get("recorrido_ds"),
        "recorrido_web_ds": recorrido.get("recorrido_web_ds"),
        "id_recorrido": recorrido.get("id_recorrido"),
        "id_hoyos": recorrido.get("id_hoyos"),
        "idresourcetype": recorrido.get("idresourcetype"),
        "idresource": recorrido.get("idresource"),
        "resourcetype": recorrido.get("resourcetype"),
        "resource": recorrido.get("resource"),
        "is_18hoyos": normalizar_bool(recorrido.get("is_18hoyos"), defecto=False),
        "is_9hoyos": normalizar_bool(recorrido.get("is_9hoyos"), defecto=False),
        "is_campo_corto": normalizar_bool(recorrido.get("is_campo_corto"), defecto=False),
        "is_rustic": normalizar_bool(recorrido.get("is_rustic"), defecto=False),
    }


def mapear_metodo_db(campo_metodo, metodo_reserva):
    metodo_cd = (metodo_reserva or {}).get("metodo_cd")
    return {
        "campo_metodo_id": campo_metodo.get("campo_metodo_id"),
        "campo_id": campo_metodo.get("campo_id"),
        "metodo_id": campo_metodo.get("metodo_id"),
        "metodo_cd": metodo_cd,
        "proveedor": (metodo_reserva or {}).get("proveedor"),
        "descripcion": (metodo_reserva or {}).get("descripcion"),
        "url_api": campo_metodo.get("url_api"),
        "url_origen_api": campo_metodo.get("url_origen_api"),
        "id_vendor": campo_metodo.get("id_vendor"),
        "id_vendor_proveedor": campo_metodo.get("id_vendor_proveedor"),
        "id_club": campo_metodo.get("id_club"),
        "id_agente": campo_metodo.get("id_agente"),
        "area": campo_metodo.get("area"),
        "activo_fl": normalizar_bool(campo_metodo.get("activo_fl"), defecto=True),
    }




@st.cache_data(ttl=0)
def cargar_campos(solo_activos=True):
    """
    Carga campos, recorridos y métodos activos desde Supabase.
    Ya no lee CamposTeeRadar.json.
    """
    try:
        campos_db = ejecutar_select_supabase(
            "camposgolf",
            "campo_id,campo_ds,municipio_id,activo_fl,consultable_fl,latitud,longitud,tfno_reserva,email_reserva,url_reserva,motivo_nocons,web_ds,tfno_ds,email_ds",
            ordenar_por="campo_ds"
        )

        recorridos_db = ejecutar_select_supabase(
            "recorridos",
            "recorrido_id,campo_id,recorrido_ds,recorrido_web_ds,id_recorrido,id_hoyos,idresourcetype,idresource,resourcetype,resource,is_18hoyos,is_9hoyos,is_campo_corto,is_rustic",
            ordenar_por="recorrido_ds"
        )

        campos_metodos_db = ejecutar_select_supabase(
            "camposgolf_metodos",
            "campo_metodo_id,campo_id,metodo_id,url_api,url_origen_api,id_vendor,id_vendor_proveedor,id_club,id_agente,area,activo_fl",
            ordenar_por="campo_metodo_id"
        )

        metodos_reserva_db = ejecutar_select_supabase(
            "metodos_reserva",
            "metodo_id,metodo_cd,proveedor,descripcion",
            ordenar_por="metodo_id"
        )

    except Exception as e:
        st.error(f"No se pudieron cargar campos/recorridos/métodos desde Supabase: {e}")
        st.stop()

    metodos_reserva_por_id = {
        metodo.get("metodo_id"): metodo
        for metodo in metodos_reserva_db
    }

    recorridos_por_campo = {}
    for recorrido in recorridos_db:
        campo_id = recorrido.get("campo_id")
        if campo_id is None:
            continue
        recorridos_por_campo.setdefault(campo_id, []).append(mapear_recorrido_db(recorrido))

    metodos_por_campo = {}
    for campo_metodo in campos_metodos_db:
        campo_id = campo_metodo.get("campo_id")
        if campo_id is None:
            continue

        metodo = mapear_metodo_db(
            campo_metodo,
            metodos_reserva_por_id.get(campo_metodo.get("metodo_id"))
        )
        metodos_por_campo.setdefault(campo_id, []).append(metodo)

    campos = []

    for campo_db in campos_db:
        campo_id = campo_db.get("campo_id")

        campo = {
            "campo_id": campo_id,
            "campo_ds": campo_db.get("campo_ds"),
            "municipio_id": campo_db.get("municipio_id"),
            "activo_fl": normalizar_bool(campo_db.get("activo_fl"), defecto=True),
            "consultable_fl": normalizar_bool(campo_db.get("consultable_fl"), defecto=True),
            "latitud": convertir_decimal_a_float(campo_db.get("latitud")),
            "longitud": convertir_decimal_a_float(campo_db.get("longitud")),
            "tfno_reserva": campo_db.get("tfno_reserva"),
            "email_reserva": campo_db.get("email_reserva"),
            "url_reserva": campo_db.get("url_reserva"),
            "motivo_nocons": campo_db.get("motivo_nocons"),
            "web_ds": campo_db.get("web_ds"),
            "tfno_ds": campo_db.get("tfno_ds"),
            "email_ds": campo_db.get("email_ds"),
            "recorridos": recorridos_por_campo.get(campo_id, []),
            "metodos": [
                metodo for metodo in metodos_por_campo.get(campo_id, [])
                if metodo.get("activo_fl")
            ]
        }

        if solo_activos and not es_campo_activo(campo):
            continue

        campos.append(campo)

    return campos


def convertir_decimal_a_float(valor):
    """
    Convierte valores numéricos recibidos desde Supabase a float.
    Supabase puede devolver numeric como Decimal, int, float o str según el cliente/entorno.
    """
    if valor is None:
        return None

    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def ejecutar_select_supabase(tabla, columnas, ordenar_por=None, page_size=1000):
    """
    Ejecuta una lectura paginada sobre una tabla Supabase.
    Evita depender del límite por defecto cuando crezca el número de municipios/campos.
    """
    supabase = obtener_cliente_supabase()
    registros = []
    inicio = 0

    while True:
        fin = inicio + page_size - 1
        query = supabase.table(tabla).select(columnas)

        if ordenar_por:
            query = query.order(ordenar_por)

        respuesta = query.range(inicio, fin).execute()
        bloque = respuesta.data or []

        registros.extend(bloque)

        if len(bloque) < page_size:
            break

        inicio += page_size

    return registros


@st.cache_data(ttl=0)
def cargar_localidades():
    """
    Carga municipios, provincias y zonas desde Supabase.

    Estructura devuelta a la UI:
    [
        {
            "municipio_id": int,
            "localidad_id": int,        # compatibilidad temporal con código existente
            "localidad": str,
            "provincia_id": int,
            "provincia": str,
            "lat": float | None,
            "lon": float | None,
            "zonas": [
                {
                    "zona_id": int,
                    "zona": str,
                    "lat": float | None,
                    "lon": float | None
                }
            ]
        }
    ]
    """
    try:
        provincias_db = ejecutar_select_supabase(
            "provincias",
            "provincia_id,provincia_ds,postal_cd",
            ordenar_por="provincia_ds"
        )

        municipios_db = ejecutar_select_supabase(
            "municipios",
            "municipio_id,municipio_ds,provincia_id,latitud,longitud",
            ordenar_por="municipio_ds"
        )

        zonas_db = ejecutar_select_supabase(
            "zonas",
            "zona_id,municipio_id,zona_ds,latitud,longitud",
            ordenar_por="zona_ds"
        )

    except Exception as e:
        st.error(f"No se pudieron cargar municipios/zonas desde Supabase: {e}")
        st.stop()

    provincias_por_id = {
        provincia.get("provincia_id"): provincia
        for provincia in provincias_db
    }

    zonas_por_municipio = {}
    for zona in zonas_db:
        municipio_id = zona.get("municipio_id")
        if municipio_id is None:
            continue

        zonas_por_municipio.setdefault(municipio_id, []).append({
            "zona_id": zona.get("zona_id"),
            "zona_id_db": zona.get("zona_id"),
            "zona": zona.get("zona_ds"),
            "zona_ds": zona.get("zona_ds"),
            "lat": convertir_decimal_a_float(zona.get("latitud")),
            "lon": convertir_decimal_a_float(zona.get("longitud"))
        })

    localidades = []

    for municipio in municipios_db:
        municipio_id = municipio.get("municipio_id")
        provincia = provincias_por_id.get(municipio.get("provincia_id"), {})

        localidad = {
            "municipio_id": municipio_id,
            "municipio_id_db": municipio_id,
            "localidad_id": municipio_id,  # compatibilidad temporal con código existente
            "localidad": municipio.get("municipio_ds"),
            "municipio_ds": municipio.get("municipio_ds"),
            "provincia_id": municipio.get("provincia_id"),
            "provincia_ds": provincia.get("provincia_ds"),
            "provincia": provincia.get("provincia_ds"),
            "lat": convertir_decimal_a_float(municipio.get("latitud")),
            "lon": convertir_decimal_a_float(municipio.get("longitud"))
        }

        zonas = zonas_por_municipio.get(municipio_id, [])
        if zonas:
            localidad["zonas"] = zonas

        localidades.append(localidad)

    localidades.sort(
        key=lambda l: (
            str(l.get("provincia") or "").lower(),
            str(l.get("localidad") or "").lower()
        )
    )

    return localidades

def recorrido_cumple_filtros(recorrido, filtro_hoyos, filtro_tipo):
    es_18 = normalizar_bool(recorrido.get("is_18hoyos"), defecto=False)
    es_9 = normalizar_bool(recorrido.get("is_9hoyos"), defecto=False)
    es_corto = normalizar_bool(recorrido.get("is_campo_corto"), defecto=False)

    if filtro_hoyos == "18" and not es_18:
        return False
    if filtro_hoyos == "9" and not es_9:
        return False
    if filtro_tipo == "corto" and not es_corto:
        return False
    if filtro_tipo == "largo" and es_corto:
        return False
    return True

def formatear_nombre_recorrido(recorrido):
    nombre = nombre_recorrido(recorrido)
    es_corto = normalizar_bool(recorrido.get("is_campo_corto"), defecto=False)
    if es_corto:
        nombre += " (Pitch & Putt)"
    return nombre

def construir_resultado(campo, recorrido, hora, jugadores_disp, tarifas, metodo=None):
    return {
        "campo_id": campo.get("campo_id"),
        "campo": nombre_campo(campo),
        "recorrido": formatear_nombre_recorrido(recorrido),
        "hora": hora,
        "jugadores_disponibles": jugadores_disp,
        "tarifas": tarifas,
        "url_reserva": obtener_url_reserva(campo, metodo) or "No disponible",
        "email_reservas": campo.get("email_reserva", "No disponible"),
        "telefono_reserva": campo.get("tfno_reserva", "No disponible"),
        "distancia_km": campo.get("distancia_ruta_km", campo.get("distancia_km")),
        "distancia_ruta_km": campo.get("distancia_ruta_km"),
        "duracion_ruta_min": campo.get("duracion_ruta_min")
    }

def es_campo_consultable(campo):
    return normalizar_bool(campo.get("consultable_fl"), defecto=True)

def construir_campo_no_consultable(campo, filtro_hoyos, filtro_tipo):
    recorridos_validos = [
        formatear_nombre_recorrido(recorrido)
        for recorrido in campo.get("recorridos", [])
        if recorrido_cumple_filtros(recorrido, filtro_hoyos, filtro_tipo)
    ]

    return {
        "campo_id": campo.get("campo_id"),
        "campo": nombre_campo(campo),
        "distancia_km": campo.get("distancia_ruta_km", campo.get("distancia_km")),
        "distancia_ruta_km": campo.get("distancia_ruta_km"),
        "duracion_ruta_min": campo.get("duracion_ruta_min"),
        "motivo_no_consultable": campo.get("motivo_nocons", "No disponible"),
        "web": campo.get("web_ds", "No disponible"),
        "email": campo.get("email_ds", "No disponible"),
        "telefono": campo.get("tfno_ds", "No disponible"),
        "recorridos": recorridos_validos
    }


@st.dialog("Info Reservas")
def mostrar_dialogo_info_reservas(resultado):
    st.markdown(f"### {resultado.get('campo', 'Campo')}")
    st.write(f"**Web reservas:** {resultado.get('url_reserva', 'No disponible')}")
    st.write(f"**Email:** {resultado.get('email_reservas', 'No disponible')}")
    st.write(f"**Teléfono:** {resultado.get('telefono_reserva', 'No disponible')}")


@st.dialog("Info del club")
def mostrar_dialogo_info_club(campo_nc):
    st.markdown(f"### {campo_nc.get('campo', 'Campo')}")
    st.write(f"**Motivo:** {campo_nc.get('motivo_no_consultable', 'No disponible')}")
    st.write(f"**Web:** {campo_nc.get('web', 'No disponible')}")
    st.write(f"**Email:** {campo_nc.get('email', 'No disponible')}")
    st.write(f"**Teléfono:** {campo_nc.get('telefono', 'No disponible')}")

    recorridos = campo_nc.get("recorridos") or []
    if recorridos:
        st.write("**Recorridos:**")
        for recorrido in recorridos:
            st.write(f"- {recorrido}")


@st.dialog("JSON completo de la caché")
def mostrar_dialogo_json_cache(cache):
    st.code(json.dumps(cache, ensure_ascii=False, indent=2), language="json")


def calcular_distancia_km(lat1, lon1, lat2, lon2):
    import math

    R = 6371

    lat1 = float(lat1)
    lon1 = float(lon1)
    lat2 = float(lat2)
    lon2 = float(lon2)

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )

    a = min(1, max(0, a))

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c

def campo_dentro_bounding_box(lat_ref, lon_ref, lat_campo, lon_campo, radio_km):
    """
    Filtro rapido previo al Haversine.
    Crea una caja aproximada alrededor de la localidad seleccionada y descarta
    campos que estan claramente fuera del radio antes de calcular la distancia real.

    Importante:
    - Este filtro NO sustituye al Haversine.
    - Solo reduce candidatos.
    - El Haversine sigue siendo el filtro definitivo.
    """
    lat_ref = float(lat_ref)
    lon_ref = float(lon_ref)
    lat_campo = float(lat_campo)
    lon_campo = float(lon_campo)
    radio_km = float(radio_km)

    # Aproximacion: 1 grado de latitud equivale a unos 111 km.
    delta_lat = radio_km / 111.0

    # La equivalencia de longitud depende de la latitud.
    cos_lat = math.cos(math.radians(lat_ref))

    # Proteccion por si alguna vez se usan coordenadas extremas cercanas a polos.
    if abs(cos_lat) < 0.000001:
        delta_lon = 180
    else:
        delta_lon = radio_km / (111.0 * cos_lat)

    return (
        lat_ref - delta_lat <= lat_campo <= lat_ref + delta_lat
        and lon_ref - delta_lon <= lon_campo <= lon_ref + delta_lon
    )

@st.cache_resource
def obtener_cliente_supabase():
    """
    Crea y reutiliza el cliente Supabase.
    Requiere estos secrets en Streamlit:
    - SUPABASE_URL
    - SUPABASE_KEY
    """
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )


@st.cache_data(ttl=0)
def cargar_mapa_camposgolf_db():
    """
    Devuelve un diccionario nombre normalizado -> campo_id real en BD.
    Importante: el campo_id del JSON ya no se usa para cache_rutas.
    """
    supabase = obtener_cliente_supabase()
    data = supabase.table("camposgolf").select("campo_id,campo_ds").execute().data or []

    mapa = {}
    for fila in data:
        nombre = fila.get("campo_ds")
        campo_id = fila.get("campo_id")
        if nombre and campo_id is not None:
            mapa[str(nombre).strip().lower()] = campo_id

    return mapa


def resolver_campo_id_db(campo):
    """
    Resuelve el campo_id real de Supabase.
    Si el campo ya viene de BD, usa directamente campo_id.
    """
    if campo.get("campo_id") is not None:
        return campo.get("campo_id")

    nombre = campo.get("campo_ds")
    if not nombre:
        return None

    try:
        mapa = cargar_mapa_camposgolf_db()
        campo_id = mapa.get(str(nombre).strip().lower())

        if campo_id is None and modo_debug:
            st.warning(f"No se pudo resolver campo_id BD para: {nombre}")

        return campo_id
    except Exception as e:
        if modo_debug:
            st.warning(f"No se pudo cargar camposgolf desde Supabase: {e}")
        return None


def resolver_provincia_id_db(provincia_ds):
    if not provincia_ds:
        return None

    try:
        supabase = obtener_cliente_supabase()
        data = supabase.table("provincias").select("provincia_id").eq(
            "provincia_ds", provincia_ds
        ).limit(1).execute().data

        if data:
            return data[0].get("provincia_id")
    except Exception as e:
        if modo_debug:
            st.warning(f"No se pudo resolver provincia en Supabase: {e}")

    return None


def resolver_municipio_id_db(origen_cache):
    if not origen_cache:
        return None

    if origen_cache.get("municipio_id_db") is not None:
        return origen_cache.get("municipio_id_db")

    municipio_ds = origen_cache.get("municipio_ds") or origen_cache.get("localidad")
    provincia_ds = origen_cache.get("provincia_ds") or origen_cache.get("provincia")

    if not municipio_ds:
        return None

    try:
        supabase = obtener_cliente_supabase()
        query = supabase.table("municipios").select("municipio_id").eq(
            "municipio_ds", municipio_ds
        )

        provincia_id = resolver_provincia_id_db(provincia_ds)
        if provincia_id is not None:
            query = query.eq("provincia_id", provincia_id)

        data = query.limit(1).execute().data

        if data:
            return data[0].get("municipio_id")
    except Exception as e:
        if modo_debug:
            st.warning(f"No se pudo resolver municipio en Supabase: {e}")

    return None


def resolver_zona_id_db(origen_cache, municipio_id_db):
    if not origen_cache or municipio_id_db is None:
        return None

    if origen_cache.get("zona_id_db") is not None:
        return origen_cache.get("zona_id_db")

    zona_ds = origen_cache.get("zona_ds") or origen_cache.get("zona")
    if not zona_ds:
        return None

    try:
        supabase = obtener_cliente_supabase()
        data = supabase.table("zonas").select("zona_id").eq(
            "municipio_id", municipio_id_db
        ).eq("zona_ds", zona_ds).limit(1).execute().data

        if data:
            return data[0].get("zona_id")
    except Exception as e:
        if modo_debug:
            st.warning(f"No se pudo resolver zona en Supabase: {e}")

    return None


def obtener_ids_origen_cache_db(origen_cache):
    municipio_id_db = resolver_municipio_id_db(origen_cache)
    zona_id_db = resolver_zona_id_db(origen_cache, municipio_id_db)
    return municipio_id_db, zona_id_db


def coord_cache_key(valor):
    """
    Normaliza coordenadas para la clave lógica de cache_rutas.
    La tabla conserva las coordenadas reales a 6 decimales y usa estas
    columnas *_key a 4 decimales para reutilizar rutas equivalentes.
    """
    if valor is None:
        return None

    try:
        return round(float(valor), 4)
    except (TypeError, ValueError):
        return None


def obtener_coordenadas_cache_ruta(origen_cache, campo):
    """
    Devuelve coordenadas reales y claves normalizadas para buscar/guardar caché.
    Si falta alguna coordenada, devuelve None.
    """
    if not origen_cache or not campo:
        return None

    try:
        lat_origen = round(float(origen_cache.get("lat")), 6)
        lon_origen = round(float(origen_cache.get("lon")), 6)
        lat_destino = round(float(get_campo_lat(campo)), 6)
        lon_destino = round(float(get_campo_lon(campo)), 6)
    except (TypeError, ValueError):
        return None

    return {
        "lat_origen": lat_origen,
        "lon_origen": lon_origen,
        "lat_destino": lat_destino,
        "lon_destino": lon_destino,
        "lat_origen_key": coord_cache_key(lat_origen),
        "lon_origen_key": coord_cache_key(lon_origen),
        "lat_destino_key": coord_cache_key(lat_destino),
        "lon_destino_key": coord_cache_key(lon_destino),
    }


def obtener_distancia_cacheada_db(origen_cache, campo):
    """
    Lee una distancia cacheada desde cache_rutas.
    La clave real de caché son las coordenadas origen/destino redondeadas a 4 decimales.
    municipio_id, zona_id, campo_id y auto_localizado quedan como datos contextuales.
    """
    coords = obtener_coordenadas_cache_ruta(origen_cache, campo)
    if not coords:
        return None

    try:
        supabase = obtener_cliente_supabase()
        data = supabase.table("cache_rutas").select(
            "cache_id,distancia_ruta_m,duracion_ruta_s,fuente,calculo_dt,lat_origen_key,lon_origen_key,lat_destino_key,lon_destino_key"
        ).eq("lat_origen_key", coords["lat_origen_key"]).eq(
            "lon_origen_key", coords["lon_origen_key"]
        ).eq("lat_destino_key", coords["lat_destino_key"]).eq(
            "lon_destino_key", coords["lon_destino_key"]
        ).limit(1).execute().data

        if not data:
            return None

        entrada = data[0]
        distancia_m = entrada.get("distancia_ruta_m")
        duracion_s = entrada.get("duracion_ruta_s")

        if distancia_m is None or duracion_s is None:
            return None

        return {
            "cache_id": entrada.get("cache_id"),
            "distancia_ruta_km": round(float(distancia_m) / 1000, 1),
            "duracion_ruta_min": round(float(duracion_s) / 60),
            "fuente": entrada.get("fuente"),
            "calculo_dt": entrada.get("calculo_dt")
        }

    except Exception as e:
        if modo_debug:
            st.warning(f"No se pudo consultar cache_rutas en Supabase: {e}")
        return None


def guardar_distancia_cacheada_db(origen_cache, campo, distancia_m, duracion_s, fuente="ORS"):
    """
    Inserta o actualiza cache_rutas.
    Guarda distancia/duración como enteros redondeados: metros y segundos.
    La búsqueda de duplicados se hace por las cuatro columnas *_key.
    """
    campo_id_db = resolver_campo_id_db(campo)
    if campo_id_db is None:
        return

    coords = obtener_coordenadas_cache_ruta(origen_cache, campo)
    if not coords:
        if modo_debug:
            st.warning("No se pudo guardar caché: coordenadas origen/destino no válidas.")
        return

    # Estos IDs ya no forman parte de la clave de caché.
    # Se guardan solo como información contextual/trazabilidad.
    municipio_id_db, zona_id_db = obtener_ids_origen_cache_db(origen_cache)

    try:
        distancia_m_int = int(round(float(distancia_m)))
        duracion_s_int = int(round(float(duracion_s)))
    except (TypeError, ValueError):
        return

    ahora = datetime.now(TZ).isoformat(timespec="seconds") if "TZ" in globals() else datetime.now().isoformat(timespec="seconds")

    registro = {
        "campo_id": campo_id_db,
        "auto_localizado": False,
        "municipio_id": municipio_id_db,
        "zona_id": zona_id_db,
        "lat_origen": coords["lat_origen"],
        "lon_origen": coords["lon_origen"],
        "lat_destino": coords["lat_destino"],
        "lon_destino": coords["lon_destino"],
        "lat_origen_key": coords["lat_origen_key"],
        "lon_origen_key": coords["lon_origen_key"],
        "lat_destino_key": coords["lat_destino_key"],
        "lon_destino_key": coords["lon_destino_key"],
        "distancia_ruta_m": distancia_m_int,
        "duracion_ruta_s": duracion_s_int,
        "fuente": fuente,
        "calculo_dt": ahora,
        "created_by": "TeeRadar",
        "updated_dt": ahora,
        "updated_by": "TeeRadar"
    }

    try:
        supabase = obtener_cliente_supabase()
        existentes = supabase.table("cache_rutas").select("cache_id").eq(
            "lat_origen_key", coords["lat_origen_key"]
        ).eq("lon_origen_key", coords["lon_origen_key"]).eq(
            "lat_destino_key", coords["lat_destino_key"]
        ).eq("lon_destino_key", coords["lon_destino_key"]).limit(1).execute().data

        if existentes:
            cache_id = existentes[0]["cache_id"]
            registro_update = dict(registro)
            registro_update.pop("created_by", None)
            supabase.table("cache_rutas").update(registro_update).eq("cache_id", cache_id).execute()
        else:
            supabase.table("cache_rutas").insert(registro).execute()

    except Exception as e:
        if modo_debug:
            st.warning(f"No se pudo guardar caché en Supabase: {e}")


def cargar_cache_distancias_ruta():
    """
    Carga cache_rutas desde Supabase para el editor/debug.
    Devuelve una estructura parecida al antiguo JSON para minimizar cambios en UI.
    """
    try:
        supabase = obtener_cliente_supabase()
        data = supabase.table("cache_rutas").select("*").order("cache_id").limit(5000).execute().data
    except Exception as e:
        if modo_debug:
            st.warning(f"No se pudo cargar cache_rutas desde Supabase: {e}")
        data = []

    distancias = {}
    for fila in data or []:
        cache_id = str(fila.get("cache_id"))
        distancia_m = fila.get("distancia_ruta_m")
        duracion_s = fila.get("duracion_ruta_s")
        distancias[cache_id] = {
            **fila,
            "distancia_ruta_km": round(float(distancia_m) / 1000, 1) if distancia_m is not None else None,
            "duracion_ruta_min": round(float(duracion_s) / 60) if duracion_s is not None else None,
            "fecha_calculo": fila.get("calculo_dt"),
            "fecha_modificacion_manual": fila.get("updated_dt"),
            "manual": str(fila.get("fuente", "")).lower() == "manual"
        }

    return {"version": 2, "origen": "supabase", "distancias": distancias}


def guardar_cache_distancias_ruta(cache):
    """
    Ya no se usa JSON. Se mantiene para no romper referencias antiguas.
    """
    return


def obtener_clave_cache_ruta(origen_cache, campo):
    """
    Clave textual solo para debug/compatibilidad.
    La búsqueda real en Supabase usa las columnas lat/lon *_key.
    """
    coords = obtener_coordenadas_cache_ruta(origen_cache, campo)
    if not coords:
        return None

    return (
        f"origen:{coords['lat_origen_key']},{coords['lon_origen_key']}|"
        f"destino:{coords['lat_destino_key']},{coords['lon_destino_key']}"
    )


def obtener_distancia_cacheada(cache, clave):
    """
    Solo usado por el editor/debug si fuera necesario.
    """
    if not clave:
        return None

    entrada = cache.get("distancias", {}).get(str(clave))
    if not isinstance(entrada, dict):
        return None

    if entrada.get("distancia_ruta_km") is None:
        return None

    return {
        "distancia_ruta_km": round(float(entrada["distancia_ruta_km"]), 1),
        "duracion_ruta_min": entrada.get("duracion_ruta_min")
    }


def actualizar_cache_distancia_ruta(cache, clave, origen_cache, campo, distancia_ruta_km, duracion_ruta_min):
    """
    Compatibilidad antigua. No se usa en la búsqueda principal.
    """
    distancia_m = round(float(distancia_ruta_km) * 1000)
    duracion_s = round(float(duracion_ruta_min) * 60) if duracion_ruta_min is not None else None
    if duracion_s is not None:
        guardar_distancia_cacheada_db(origen_cache, campo, distancia_m, duracion_s)


def pintar_editor_cache_distancias():
    """
    Editor interno para modo debug.
    Lee, modifica o elimina entradas de cache_rutas en Supabase.
    """
    cache = cargar_cache_distancias_ruta()
    distancias = cache.get("distancias", {})

    st.markdown("### 🧪 Editor caché distancias")

    total_entradas = len(distancias)
    st.caption(f"Origen: Supabase · Tabla: cache_rutas · Entradas: {total_entradas}")

    st.download_button(
        "Descargar caché distancias",
        data=json.dumps(cache, ensure_ascii=False, indent=2),
        file_name="cache_rutas_supabase.json",
        mime="application/json",
        key="descargar_cache_distancias"
    )

    if not distancias:
        st.info("La caché de distancias está vacía. Ejecuta una búsqueda con localidad/radio para generar entradas.")
        return

    try:
        supabase = obtener_cliente_supabase()
        campos_db = supabase.table("camposgolf").select("campo_id,campo_ds").execute().data or []
        nombres_por_campo_id = {str(c["campo_id"]): c.get("campo_ds", f"Campo ID {c['campo_id']}") for c in campos_db}
    except Exception:
        nombres_por_campo_id = {}

    def etiqueta_entrada(clave):
        entrada = distancias.get(clave, {})
        campo_id = entrada.get("campo_id")
        nombre_campo = nombres_por_campo_id.get(str(campo_id), f"Campo ID {campo_id}")
        municipio_id = entrada.get("municipio_id")
        zona_id = entrada.get("zona_id")
        distancia = entrada.get("distancia_ruta_km")
        marca_manual = " · manual" if entrada.get("manual") else ""
        return f"{nombre_campo} · mun {municipio_id} · zona {zona_id} · {distancia} km{marca_manual}"

    claves_ordenadas = sorted(distancias.keys(), key=etiqueta_entrada)

    clave_seleccionada = st.selectbox(
        "Entrada cacheada",
        options=claves_ordenadas,
        format_func=etiqueta_entrada,
        key="cache_distancias_clave_seleccionada"
    )

    entrada = distancias.get(clave_seleccionada, {})

    col_info_1, col_info_2, col_info_3 = st.columns(3)
    with col_info_1:
        st.text_input("cache_id", value=str(entrada.get("cache_id")), disabled=True)
        st.text_input("campo_id", value=str(entrada.get("campo_id")), disabled=True)
    with col_info_2:
        st.text_input("municipio_id", value=str(entrada.get("municipio_id")), disabled=True)
        st.text_input("zona_id", value=str(entrada.get("zona_id")), disabled=True)
    with col_info_3:
        st.text_input("fuente", value=str(entrada.get("fuente", "--")), disabled=True)
        st.text_input("calculo_dt", value=str(entrada.get("calculo_dt", "--")), disabled=True)

    col_coord_1, col_coord_2 = st.columns(2)
    with col_coord_1:
        st.text_input("lat/lon origen", value=f"{entrada.get('lat_origen')}, {entrada.get('lon_origen')}", disabled=True)
        st.text_input("lat/lon origen key", value=f"{entrada.get('lat_origen_key')}, {entrada.get('lon_origen_key')}", disabled=True)
    with col_coord_2:
        st.text_input("lat/lon destino", value=f"{entrada.get('lat_destino')}, {entrada.get('lon_destino')}", disabled=True)
        st.text_input("lat/lon destino key", value=f"{entrada.get('lat_destino_key')}, {entrada.get('lon_destino_key')}", disabled=True)

    distancia_actual = entrada.get("distancia_ruta_km", 0)
    duracion_actual = entrada.get("duracion_ruta_min", 0)

    try:
        distancia_actual = float(distancia_actual)
    except (TypeError, ValueError):
        distancia_actual = 0.0

    try:
        duracion_actual = int(round(float(duracion_actual))) if duracion_actual is not None else 0
    except (TypeError, ValueError):
        duracion_actual = 0

    col_edit_1, col_edit_2 = st.columns(2)
    with col_edit_1:
        nueva_distancia = st.number_input(
            "Distancia ruta km",
            min_value=0.0,
            value=round(distancia_actual, 1),
            step=0.1,
            format="%.1f",
            key=f"cache_distancias_nueva_distancia_{clave_seleccionada}"
        )
    with col_edit_2:
        nueva_duracion = st.number_input(
            "Duración ruta min",
            min_value=0,
            value=duracion_actual,
            step=1,
            key=f"cache_distancias_nueva_duracion_{clave_seleccionada}"
        )

    col_btn_1, col_btn_2 = st.columns(2)
    with col_btn_1:
        if st.button("Guardar cambios caché", key="guardar_cambios_cache_distancias"):
            try:
                supabase = obtener_cliente_supabase()
                ahora = datetime.now(TZ).isoformat(timespec="seconds") if "TZ" in globals() else datetime.now().isoformat(timespec="seconds")
                supabase.table("cache_rutas").update({
                    "distancia_ruta_m": int(round(float(nueva_distancia) * 1000)),
                    "duracion_ruta_s": int(round(float(nueva_duracion) * 60)),
                    "fuente": "manual",
                    "calculo_dt": ahora,
                    "updated_dt": ahora,
                    "updated_by": "TeeRadar"
                }).eq("cache_id", int(entrada.get("cache_id"))).execute()
                st.success("Caché actualizada en Supabase.")
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo actualizar la caché en Supabase: {e}")

    with col_btn_2:
        if st.button("Eliminar entrada caché", key="eliminar_entrada_cache_distancias"):
            try:
                supabase = obtener_cliente_supabase()
                supabase.table("cache_rutas").delete().eq("cache_id", int(entrada.get("cache_id"))).execute()
                st.success("Entrada eliminada de Supabase.")
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo eliminar la entrada de Supabase: {e}")

    if st.button("Ver JSON completo de la caché", key="ver_json_completo_cache_distancias"):
        mostrar_dialogo_json_cache(cache)


def calcular_distancias_ruta_heigit(lat_ref, lon_ref, campos, radio_km, origen_cache=None):
    """
    Calcula distancia en ruta para campos que ya han pasado Bounding Box + Haversine.
    Primero intenta reutilizar cache_rutas en Supabase.
    Solo llama a HeiGIT/OpenRouteService Matrix API para los campos que no están cacheados.
    Devuelve dos listas: campos_en_rango_ruta y campos_fuera_ruta.
    """
    if not campos:
        return [], []

    try:
        lat_ref_float = float(lat_ref)
        lon_ref_float = float(lon_ref)
        radio_km_float = float(radio_km)
    except (TypeError, ValueError):
        if modo_debug:
            st.warning("No se pudo calcular distancia en ruta: origen o radio no válido.")
        return campos, []

    campos_en_rango_ruta = []
    campos_fuera_ruta = []
    campos_pendientes_ors = []
    locations = [[lon_ref_float, lat_ref_float]]

    origen_txt = f"{lat_ref_float:.6f}, {lon_ref_float:.6f}"

    for campo in campos:
        try:
            lat_campo = float(get_campo_lat(campo))
            lon_campo = float(get_campo_lon(campo))
        except (TypeError, ValueError):
            registrar_debug_filtro(
                campo,
                campo_activo="OK",
                recorrido_hoyos="OK",
                bounding_box="OK",
                haversine=f"OK - {campo.get('distancia_km', 0):.1f} km".replace('.', ','),
                matrix_ors="KO - coordenadas no válidas",
                origen="--",
                destino="--",
                resultado="Fuera de rango"
            )
            continue

        destino_txt = f"{lat_campo:.6f}, {lon_campo:.6f}"
        distancia_cacheada = obtener_distancia_cacheada_db(origen_cache, campo)

        if distancia_cacheada is not None:
            distancia_ruta_km = distancia_cacheada["distancia_ruta_km"]
            campo["distancia_ruta_km"] = distancia_ruta_km

            if distancia_cacheada.get("duracion_ruta_min") is not None:
                campo["duracion_ruta_min"] = distancia_cacheada["duracion_ruta_min"]

            if distancia_ruta_km <= radio_km_float:
                matrix_txt = f"OK caché - {distancia_ruta_km:.1f} km ruta".replace('.', ',')
                resultado_txt = "En rango"
                campos_en_rango_ruta.append(campo)
            else:
                matrix_txt = f"KO caché - {distancia_ruta_km:.1f} km ruta".replace('.', ',')
                resultado_txt = "Fuera de rango"
                campos_fuera_ruta.append(campo)

            registrar_debug_filtro(
                campo,
                campo_activo="OK",
                recorrido_hoyos="OK",
                bounding_box="OK",
                haversine=f"OK - {campo.get('distancia_km', 0):.1f} km".replace('.', ','),
                matrix_ors=matrix_txt,
                origen=origen_txt,
                destino=destino_txt,
                resultado=resultado_txt
            )
            continue

        locations.append([lon_campo, lat_campo])
        campos_pendientes_ors.append(campo)

    if not campos_pendientes_ors:
        return campos_en_rango_ruta, campos_fuera_ruta

    try:
        api_key = st.secrets["HEIGIT_API_KEY"]
    except Exception:
        if modo_debug:
            st.warning("No se encuentra HEIGIT_API_KEY en Streamlit Secrets.")
        return campos_en_rango_ruta + campos_pendientes_ors, campos_fuera_ruta

    payload = {
        "locations": locations,
        "sources": [0],
        "destinations": list(range(1, len(locations))),
        "metrics": ["distance", "duration"],
        "units": "m"
    }

    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json"
    }

    url = "https://api.heigit.org/openrouteservice/v2/matrix/driving-car"

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        data = r.json()

        if r.status_code != 200:
            if modo_debug:
                st.warning(f"Error Matrix ORS/HeiGIT ({r.status_code}): {data}")
            return campos_en_rango_ruta + campos_pendientes_ors, campos_fuera_ruta

        distancias = data.get("distances", [[]])[0]
        duraciones = data.get("durations", [[]])[0]

    except Exception as e:
        if modo_debug:
            st.warning(f"Error llamando a Matrix ORS/HeiGIT: {e}")
        return campos_en_rango_ruta + campos_pendientes_ors, campos_fuera_ruta

    for i, campo in enumerate(campos_pendientes_ors):
        distancia_m = distancias[i] if i < len(distancias) else None
        duracion_s = duraciones[i] if i < len(duraciones) else None

        try:
            lat_campo = float(get_campo_lat(campo))
            lon_campo = float(get_campo_lon(campo))
        except (TypeError, ValueError):
            lat_campo = None
            lon_campo = None

        if distancia_m is None or duracion_s is None:
            registrar_debug_filtro(
                campo,
                campo_activo="OK",
                recorrido_hoyos="OK",
                bounding_box="OK",
                haversine=f"OK - {campo.get('distancia_km', 0):.1f} km".replace('.', ','),
                matrix_ors="KO - sin distancia/duración",
                origen="--",
                destino="--",
                resultado="Fuera de rango"
            )
            campos_fuera_ruta.append(campo)
            continue

        distancia_ruta_km = round(float(distancia_m) / 1000, 1)
        campo["distancia_ruta_km"] = distancia_ruta_km

        duracion_ruta_min = round(float(duracion_s) / 60)
        campo["duracion_ruta_min"] = duracion_ruta_min

        guardar_distancia_cacheada_db(
            origen_cache,
            campo,
            distancia_m,
            duracion_s,
            fuente="ORS"
        )

        destino_txt = f"{lat_campo:.6f}, {lon_campo:.6f}" if lat_campo is not None and lon_campo is not None else "--"

        if distancia_ruta_km <= radio_km_float:
            matrix_txt = f"OK ORS - {distancia_ruta_km:.1f} km ruta".replace('.', ',')
            resultado_txt = "En rango"
            campos_en_rango_ruta.append(campo)
        else:
            matrix_txt = f"NO caché - {distancia_ruta_km:.1f} km ruta".replace('.', ',')
            resultado_txt = "Fuera de rango"
            campos_fuera_ruta.append(campo)

        registrar_debug_filtro(
            campo,
            campo_activo="OK",
            recorrido_hoyos="OK",
            bounding_box="OK",
            haversine=f"OK - {campo.get('distancia_km', 0):.1f} km".replace('.', ','),
            matrix_ors=matrix_txt,
            origen=origen_txt,
            destino=destino_txt,
            resultado=resultado_txt
        )

    return campos_en_rango_ruta, campos_fuera_ruta



def consultar_recorrido_teeone_v1(session, campo, metodo, recorrido, token, id_inicio, api, culture,
                                  fecha, hora_inicio, hora_fin, jugadores):
    payload = {
        "culture": culture,
        "fecha": fecha,
        "horaFin": hora_fin,
        "horaInicio": hora_inicio,
        "idInicioSesion": id_inicio,
        "idRecorrido": str(recorrido["id_recorrido"]),
        "idTarifaTipoUso": 1,
        "idVendedor": str(metodo.get("id_vendor")),
        "idVendedorProveedor": str(metodo.get("id_vendor_proveedor")),
        "idVendedorTourOperador": "-1",
        "jugadores": "-1",
        "pageNum": -1,
        "pageSize": 50,
        "precioFin": "2000",
        "precioInicio": "1",
        "promoCode": "",
        "Token": token
    }

    headers = {
        "Content-Type": "application/json",
        "Origin": "https://open.teeone.golf",
        "Referer": "https://open.teeone.golf/",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        registrar_debug("payload", campo, recorrido, payload)

        r = session.post(
            api + "/Api/Disponibilidad/ObtenerDisponibilidadDia",
            json=payload,
            headers=headers,
            timeout=20
        )
        data = r.json()

        registrar_debug("response", campo, recorrido, data)

    except Exception as e:
        registrar_debug("response", campo, recorrido, {"error": str(e)})
        return []

    horas = data.get("horasDisponibles")
    if not horas:
        return []

    resultados = []

    for h in horas:
        hora = h.get("hora")
        jugadores_disp = h.get("jugadoresDisponibles", 0)

        if not hora or jugadores_disp < jugadores:
            continue

        tarifas = [
            {"nombre": t.get("nombre"), "precio": t.get("precio")}
            for t in h.get("tarifas", [])
        ]

        if tarifas:
            resultados.append(
                construir_resultado(campo, recorrido, hora, jugadores_disp, tarifas, metodo)
            )

    return resultados

def consultar_campo_teeone_v1(campo, metodo, fecha, hora_inicio, hora_fin, jugadores, filtro_hoyos, filtro_tipo):
    resultados = []
    session = requests.Session()

    try:
        url_origen = metodo.get("url_origen_api") or obtener_url_reserva(campo, metodo)

        r = session.get(url_origen, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        token = obtener_valor_hidden(soup, "HidTokenAPI")
        id_inicio = obtener_valor_hidden(soup, "HidInicioSesion")
        api = obtener_valor_hidden(soup, "HidAPIDominio")
        culture = obtener_valor_hidden(soup, "HidCultura")

        if not token or not api:
            return []
    except Exception:
        return []

    for recorrido in campo.get("recorridos", []):
        if not recorrido.get("id_recorrido"):
            continue
        if not recorrido_cumple_filtros(recorrido, filtro_hoyos, filtro_tipo):
            continue

        resultados.extend(
            consultar_recorrido_teeone_v1(
                session, campo, metodo, recorrido, token, id_inicio, api, culture,
                fecha, hora_inicio, hora_fin, jugadores
            )
        )

    return resultados

def extraer_lista_ofertas_v2(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []

    for clave in (
        "ofertas", "Ofertas", "data", "Data", "items", "Items",
        "result", "Result", "results", "Results", "horasDisponibles"
    ):
        valor = data.get(clave)
        if isinstance(valor, list):
            return valor
        if isinstance(valor, dict):
            sublista = extraer_lista_ofertas_v2(valor)
            if sublista:
                return sublista

    return []

def normalizar_hora(hora):
    if not hora:
        return None
    hora = str(hora).strip()
    if "T" in hora:
        hora = hora.split("T")[-1]
    if len(hora) >= 5:
        return hora[:5]
    return None

def consultar_recorrido_teeone_v2(session, campo, metodo, recorrido, fecha, hora_inicio, hora_fin, jugadores):
    endpoint = metodo.get("url_api")
    if not endpoint:
        return []

    payload = {
        "culture": "es-ES",
        "fecha": fecha,
        "horaInicio": hora_inicio,
        "horaFin": hora_fin,
        "hoyos": str(recorrido.get("id_hoyos")),
        "idAgente": str(metodo.get("id_agente")),
        "idClub": str(metodo.get("id_club")),
        "idRecorrido": str(recorrido.get("id_recorrido")),
        "jugadores": str(jugadores),
        "pageNum": 1,
        "pageSize": 10,
        "precioFin": "130",
        "precioInicio": "10"
    }

    headers = {
        "Content-Type": "application/json",
        "Origin": "https://centronacional.teeone.golf",
        "Referer": obtener_url_reserva(campo, metodo) or "",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        registrar_debug("payload", campo, recorrido, payload)

        r = session.post(endpoint, json=payload, headers=headers, timeout=20)
        data = r.json()

        registrar_debug("response", campo, recorrido, data)

    except Exception as e:
        registrar_debug("response", campo, recorrido, {"error": str(e)})
        return []

    horas = data.get("horasDisponibles")
    if not horas:
        return []

    resultados = []

    for h in horas:
        hora = h.get("hora")
        jugadores_disp = h.get("jugadoresDisponibles", 0)

        if not hora or jugadores_disp < jugadores:
            continue

        tarifas = []

        for t in h.get("tarifas", []):
            precio = t.get("precio")

            if precio is None:
                continue

            tarifas.append({
                "nombre": t.get("nombre", "Tarifa"),
                "precio": precio
            })

        if tarifas:
            resultados.append(
                construir_resultado(campo, recorrido, hora, jugadores_disp, tarifas, metodo)
            )

    return resultados

def consultar_campo_teeone_v2(campo, metodo, fecha, hora_inicio, hora_fin, jugadores, filtro_hoyos, filtro_tipo):
    resultados = []
    session = requests.Session()

    try:
        session.get(obtener_url_reserva(campo, metodo) or "", timeout=20)
    except Exception:
        pass

    for recorrido in campo.get("recorridos", []):
        if not recorrido.get("id_recorrido"):
            continue
        if not recorrido_cumple_filtros(recorrido, filtro_hoyos, filtro_tipo):
            continue

        resultados.extend(
            consultar_recorrido_teeone_v2(
                session, campo, metodo, recorrido,
                fecha, hora_inicio, hora_fin, jugadores
            )
        )

    return resultados

def tarifa_cumple_filtro_hoyos_golfmanager(tarifa, filtro_hoyos):
    """
    Golfmanager puede devolver varias tarifas para la misma hora:
    por ejemplo GF 9 hoyos y GF 18 hoyos.
    Si la respuesta trae tags como 9holes/18holes, los usamos para filtrar.
    Si no trae tags, no descartamos la tarifa.
    """
    if filtro_hoyos not in ("18", "9"):
        return True

    tags = tarifa.get("tags") or tarifa.get("apiTags") or []
    if not isinstance(tags, list):
        tags = []

    tags_normalizados = [str(tag).lower() for tag in tags]

    if "18holes" in tags_normalizados or "9holes" in tags_normalizados:
        if filtro_hoyos == "18":
            return "18holes" in tags_normalizados
        if filtro_hoyos == "9":
            return "9holes" in tags_normalizados

    nombre = str(tarifa.get("name") or tarifa.get("priceName") or "").lower()

    if "18" in nombre or "9" in nombre:
        if filtro_hoyos == "18":
            return "18" in nombre
        if filtro_hoyos == "9":
            return "9" in nombre

    return True

def consultar_campo_golfmanager(campo, metodo, fecha, hora_inicio, hora_fin, jugadores, filtro_hoyos, filtro_tipo):
    resultados = []
    endpoint = metodo.get("url_api")

    if not endpoint:
        return []

    recorridos_validos = [
        recorrido
        for recorrido in campo.get("recorridos", [])
        if recorrido_cumple_filtros(recorrido, filtro_hoyos, filtro_tipo)
    ]

    if not recorridos_validos:
        return []

    fecha_golfmanager = str(fecha).replace("/", "-")

    headers = {
        "Accept": "*/*",
        "Referer": obtener_url_reserva(campo, metodo) or "",
        "User-Agent": "Mozilla/5.0",
        "clienturl": "/consumer/ebookings?i=1&resourcetype=1"
    }

    session = requests.Session()

    try:
        # Llamada previa para que Golfmanager pueda generar cookies de sesión si las necesita.
        url_reserva = obtener_url_reserva(campo, metodo)
        if url_reserva:
            session.get(url_reserva, headers=headers, timeout=20)
    except Exception:
        # Si falla la llamada previa, no detenemos la búsqueda.
        pass

    for recorrido in recorridos_validos:
        id_resource_type = recorrido.get("idresourcetype") or recorrido.get("resourcetype") or "1"
        id_resource = recorrido.get("idresource") or recorrido.get("resource")

        params = {
            "idResourceType": id_resource_type,
            "start": f"{fecha_golfmanager}T{hora_inicio}:00",
            "cachebreaker": int(datetime.now().timestamp() * 1000)
        }

        if id_resource is not None:
            params["idResource"] = id_resource

        try:
            registrar_debug("payload", campo, recorrido, params)

            r = session.get(endpoint, params=params, headers=headers, timeout=20)
            data = r.json()

            registrar_debug("response", campo, recorrido, data)

        except Exception as e:
            registrar_debug("response", campo, recorrido, {"error": str(e)})
            continue

        availability = data.get("availability", [])

        if isinstance(availability, dict):
            availability = list(availability.values())

        if not isinstance(availability, list):
            registrar_debug("response", campo, recorrido, {
                "error": "availability no es una lista",
                "availability": availability
            })
            continue

        if not availability:
            continue

        for slot in availability:
            if not isinstance(slot, dict):
                registrar_debug("response", campo, recorrido, {
                    "aviso": "Elemento availability ignorado porque no es un diccionario",
                    "valor": slot
                })
                continue

            hora = normalizar_hora(slot.get("date") or slot.get("start"))
            jugadores_disp = slot.get("slots", 0)

            if not hora:
                continue

            try:
                jugadores_disp = int(jugadores_disp)
            except (TypeError, ValueError):
                jugadores_disp = 0

            if jugadores_disp < jugadores:
                continue

            if hora < hora_inicio or hora > hora_fin:
                continue

            tarifas = []

            tipos = slot.get("types", [])
            if not isinstance(tipos, list):
                tipos = []

            for tipo in tipos:
                if not isinstance(tipo, dict):
                    continue

                if tipo.get("onlyMembers", False):
                    continue

                if not tarifa_cumple_filtro_hoyos_golfmanager(tipo, filtro_hoyos):
                    continue

                precio = tipo.get("price")
                if precio is None:
                    continue

                tarifas.append({
                    "nombre": (tipo.get("name") or tipo.get("priceName") or "Tarifa").strip(),
                    "precio": precio
                })

            if tarifas:
                resultados.append(
                    construir_resultado(campo, recorrido, hora, jugadores_disp, tarifas, metodo)
                )

    return resultados

def consultar_campo_golfmanager_v2(campo, metodo, fecha, hora_inicio, hora_fin, jugadores, filtro_hoyos, filtro_tipo):
    resultados = []
    endpoint = metodo.get("url_api")

    if not endpoint:
        return []

    recorridos_validos = [
        recorrido
        for recorrido in campo.get("recorridos", [])
        if recorrido_cumple_filtros(recorrido, filtro_hoyos, filtro_tipo)
    ]

    if not recorridos_validos:
        return []

    recorrido = recorridos_validos[0]

    fecha_golfmanager = str(fecha).replace("/", "-")

    params = {
        "date": f"{fecha_golfmanager}T{hora_inicio}",
        "area": metodo.get("area") or 100,
        "participants": jugadores
    }

    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Referer": obtener_url_reserva(campo, metodo) or ""
    }

    session = requests.Session()

    try:
        registrar_debug("payload", campo, recorrido, params)

        r = session.get(endpoint, params=params, headers=headers, timeout=20)
        data = r.json()

        registrar_debug("response", campo, recorrido, data)

    except Exception as e:
        registrar_debug("response", campo, recorrido, {"error": str(e)})
        return []

    items = data.get("items", [])

    if not isinstance(items, list):
        registrar_debug("response", campo, recorrido, {
            "error": "items no es una lista",
            "items": items
        })
        return []

    resultados_agrupados = {}

    for item in items:
        if not isinstance(item, dict):
            continue

        hora = normalizar_hora(item.get("start"))
        jugadores_disp = item.get("slots", 0)

        if not hora:
            continue

        try:
            jugadores_disp = int(jugadores_disp)
        except (TypeError, ValueError):
            jugadores_disp = 0

        if jugadores_disp < jugadores:
            continue

        if hora < hora_inicio or hora > hora_fin:
            continue

        if not tarifa_cumple_filtro_hoyos_golfmanager(item, filtro_hoyos):
            continue

        precio = item.get("price")
        if precio is None:
            continue

        clave = (
            hora,
            item.get("resourceName", ""),
            jugadores_disp
        )

        if clave not in resultados_agrupados:
            resultados_agrupados[clave] = {
                "hora": hora,
                "jugadores_disponibles": jugadores_disp,
                "tarifas": []
            }

        resultados_agrupados[clave]["tarifas"].append({
            "nombre": (item.get("name") or item.get("categoryName") or "Tarifa").strip(),
            "precio": precio
        })

    for grupo in resultados_agrupados.values():
        resultados.append(
            construir_resultado(
                campo,
                recorrido,
                grupo["hora"],
                grupo["jugadores_disponibles"],
                grupo["tarifas"],
                metodo
            )
        )

    return resultados

def buscar_teetimes(fecha, hora_inicio, hora_fin, jugadores, filtro_hoyos, filtro_tipo, campos_seleccionados=None, lat_ref=None, lon_ref=None, radio_km=None, origen_cache=None):
    # Cargamos todos para poder reflejar también el filtro "Campo activo" en el debug.
    # En modo normal, los inactivos se descartan inmediatamente sin más procesamiento.
    campos = cargar_campos(solo_activos=False)

    if campos_seleccionados is not None:
        campos = [
            campo for campo in campos
            if nombre_campo(campo) in campos_seleccionados
        ]

    campos_activos = []

    for campo in campos:
        if es_campo_activo(campo):
            campos_activos.append(campo)
        else:
            registrar_debug_filtro(
                campo,
                campo_activo="KO",
                bounding_box="--",
                recorrido_hoyos="--",
                haversine="--",
                matrix_ors="--",
                origen="--",
                destino="--",
                resultado="Fuera de rango"
            )

    campos = campos_activos

    if lat_ref is not None and lon_ref is not None and radio_km is not None:
        campos_en_bounding_box = []
        campos_tras_recorrido_hoyos = []
        campos_en_haversine = []

        try:
            lat_ref_float = float(lat_ref)
            lon_ref_float = float(lon_ref)
            radio_km_float = float(radio_km)
        except (TypeError, ValueError):
            if modo_debug:
                st.warning("No se pudo calcular distancia: localidad o radio con formato no válido.")
            lat_ref_float = None
            lon_ref_float = None
            radio_km_float = None

        if lat_ref_float is not None and lon_ref_float is not None and radio_km_float is not None:
            for campo in campos:
                lat_campo_original = get_campo_lat(campo)
                lon_campo_original = get_campo_lon(campo)

                try:
                    lat_campo = float(lat_campo_original)
                    lon_campo = float(lon_campo_original)
                except (TypeError, ValueError):
                    if modo_debug:
                        st.warning(f"Campo sin coordenadas válidas: {nombre_campo(campo)}")
                    registrar_debug_filtro(
                        campo,
                        campo_activo="OK",
                        recorrido_hoyos="--",
                        bounding_box="KO - coordenadas no válidas",
                        haversine="--",
                        matrix_ors="--",
                        origen="--",
                        destino="--",
                        resultado="Fuera de rango"
                    )
                    continue

                pasa_bbox = campo_dentro_bounding_box(
                    lat_ref_float,
                    lon_ref_float,
                    lat_campo,
                    lon_campo,
                    radio_km_float
                )

                if not pasa_bbox:
                    registrar_debug_filtro(
                        campo,
                        campo_activo="OK",
                        recorrido_hoyos="--",
                        bounding_box="KO",
                        haversine="--",
                        matrix_ors="--",
                        origen="--",
                        destino="--",
                        resultado="Fuera de rango"
                    )
                    continue

                campos_en_bounding_box.append(campo)

                tiene_recorrido_valido = any(
                    recorrido_cumple_filtros(
                        recorrido,
                        filtro_hoyos,
                        filtro_tipo
                    )
                    for recorrido in campo.get("recorridos", [])
                )

                if not tiene_recorrido_valido:
                    registrar_debug_filtro(
                        campo,
                        campo_activo="OK",
                        recorrido_hoyos="KO",
                        bounding_box="OK",
                        haversine="--",
                        matrix_ors="--",
                        origen="--",
                        destino="--",
                        resultado="Fuera de rango"
                    )
                    continue

                campos_tras_recorrido_hoyos.append(campo)

                distancia = calcular_distancia_km(
                    lat_ref_float,
                    lon_ref_float,
                    lat_campo,
                    lon_campo
                )

                if distancia > radio_km_float:
                    registrar_debug_filtro(
                        campo,
                        campo_activo="OK",
                        recorrido_hoyos="OK",
                        bounding_box="OK",
                        haversine=f"KO - {distancia:.1f} km".replace('.', ','),
                        matrix_ors="--",
                        origen="--",
                        destino="--",
                        resultado="Fuera de rango"
                    )
                    continue

                campo["distancia_km"] = distancia
                campos_en_haversine.append(campo)

            campos_en_rango_ruta, campos_fuera_ruta = calcular_distancias_ruta_heigit(
                lat_ref_float,
                lon_ref_float,
                campos_en_haversine,
                radio_km_float,
                origen_cache
            )

            if modo_debug:
                st.write("🧪 DEBUG RESUMEN FILTROS", {
                    "campos_tras_activos_y_debug": len(campos),
                    "campos_tras_bounding_box": len(campos_en_bounding_box),
                    "campos_tras_recorrido_hoyos": len(campos_tras_recorrido_hoyos),
                    "campos_tras_haversine": len(campos_en_haversine),
                    "campos_en_rango_ruta": len(campos_en_rango_ruta),
                    "campos_fuera_ruta": len(campos_fuera_ruta),
                    "radio_km": radio_km_float
                })

            campos = campos_en_rango_ruta

    resultados = []
    campos_no_consultables = []

    for campo in campos:
        if not es_campo_consultable(campo):
            campos_no_consultables.append(
                construir_campo_no_consultable(campo, filtro_hoyos, filtro_tipo)
            )
            continue

        metodos_activos = obtener_metodos_activos(campo)

        if not metodos_activos:
            if modo_debug:
                st.warning(f"Campo sin método activo configurado: {nombre_campo(campo)}")
            continue

        for metodo in metodos_activos:
            metodo_cd = metodo.get("metodo_cd")

            if metodo_cd == "teeone_v1":
                resultados.extend(
                    consultar_campo_teeone_v1(
                        campo, metodo, fecha, hora_inicio, hora_fin, jugadores,
                        filtro_hoyos, filtro_tipo
                    )
                )
            elif metodo_cd == "teeone_v2":
                resultados.extend(
                    consultar_campo_teeone_v2(
                        campo, metodo, fecha, hora_inicio, hora_fin, jugadores,
                        filtro_hoyos, filtro_tipo
                    )
                )
            elif metodo_cd == "golfmanager":
                resultados.extend(
                    consultar_campo_golfmanager(
                        campo, metodo, fecha, hora_inicio, hora_fin, jugadores,
                        filtro_hoyos, filtro_tipo
                    )
                )
            elif metodo_cd == "golfmanager_v2":
                resultados.extend(
                    consultar_campo_golfmanager_v2(
                        campo, metodo, fecha, hora_inicio, hora_fin, jugadores,
                        filtro_hoyos, filtro_tipo
                    )
                )
            elif modo_debug:
                st.warning(f"Método no soportado para {nombre_campo(campo)}: {metodo_cd}")

    resultados_ordenados = sorted(resultados, key=lambda r: (r["campo"], convertir_hora(r["hora"])))
    campos_no_consultables_ordenados = sorted(
        campos_no_consultables,
        key=lambda c: (c.get("distancia_km") is None, c.get("distancia_km") or 999999, c.get("campo", ""))
    )

    return resultados_ordenados, campos_no_consultables_ordenados

# =========================
# INTERFAZ
# =========================

st.markdown("<div class='subtitle'>Busca salidas disponibles en campos de golf cercanos.</div>", unsafe_allow_html=True)

st.markdown("""
<style>
.main-title {
    font-size: 34px;
    font-weight: 800;
    margin-bottom: 4px;
}

.subtitle {
    font-size: 17px;
    color: #666;
    margin-bottom: 24px;
}

.search-title {
    font-size: 26px;
    font-weight: 700;
    color: #1f2933;
    margin-bottom: 18px;
    line-height: 1.2;
}
.search-panel {
    border: 1px solid #e5e5e5;
    border-radius: 18px;
    padding: 20px;
    margin-bottom: 24px;
    background-color: #fafafa;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}

.result-summary {
    border-radius: 14px;
    padding: 12px 16px;
    margin: 16px 0 22px 0;
    background-color: #eaf7ef;
    color: #145c32;
    font-weight: 700;
}

.result-card {
    border: 1px solid #d8eadc;
    border-radius: 18px;
    padding: 16px;
    margin-bottom: 4px;
    background-color: #f3faf5;
    box-shadow: 0 3px 10px rgba(0,0,0,0.06);
    min-height: 285px;
}

.result-title {
    font-size: 19px;
    font-weight: 800;
    margin-bottom: 10px;
    color: #222;
}

.result-meta {
    font-size: 17px;
    margin-bottom: 10px;
    color: #333;
}

.result-recorrido {
    font-size: 15px;
    margin-bottom: 12px;
    color: #555;
    min-height: 38px;
}

.tarifas-title {
    font-size: 15px;
    font-weight: 700;
    margin-bottom: 6px;
}

.tarifa {
    font-size: 14px;
    margin-bottom: 5px;
    color: #333;
}

hr.card-separator {
    border: none;
    border-top: 1px solid #eee;
    margin: 12px 0;
}

.other-fields-section {
    margin-top: 30px;
    margin-bottom: 10px;
}

.other-fields-title {
    font-size: 22px;
    font-weight: 800;
    color: #222;
    margin-bottom: 2px;
}

.other-fields-subtitle {
    font-size: 14px;
    color: #666;
    margin-bottom: 16px;
}

.other-field-card {
    border: 1px solid #f0dfc8;
    border-radius: 14px 14px 8px 8px;
    padding: 12px 14px;
    margin-bottom: 4px;
    background-color: #fff8f1;
    box-shadow: 0 1px 5px rgba(0,0,0,0.04);
    min-height: 82px;
}

.other-field-title {
    font-size: 16px;
    font-weight: 800;
    color: #222;
    margin-bottom: 6px;
}

.other-field-meta {
    font-size: 14px;
    color: #444;
}

/* Botones de información bajo tarjetas de resultados */
div.stButton > button[kind="secondary"] {
    border-radius: 10px;
    border: 1px solid #d8eadc;
    background-color: #f3faf5;
    color: #276b0f;
    font-weight: 700;
    font-size: 14px;
    min-height: 36px;
    margin-top: -2px;
    margin-bottom: 12px;
}

div.stButton > button[kind="secondary"]:hover {
    border-color: #b9d3b2;
    background-color: #eaf7ef;
    color: #1f5f12;
}

div.stButton > button[kind="tertiary"] {
    border-radius: 10px;
    border: 1px solid #f0dfc8;
    background-color: #fff8f1;
    color: #7a4a12;
    font-weight: 700;
    font-size: 14px;
    min-height: 36px;
    margin-top: -2px;
    margin-bottom: 12px;
}

div.stButton > button[kind="tertiary"]:hover {
    border-color: #e2c99e;
    background-color: #fff1df;
    color: #633b0d;
}

.footer-contact {
    text-align: center;
    margin-top: 10px;
    margin-bottom: 20px;
    font-size: 0.85rem;
    color: #666;
    line-height: 1.5;
}

.footer-contact a {
    color: #276b0f;
    text-decoration: none;
    font-weight: 500;
}

.footer-contact a:hover {
    text-decoration: underline;
}
</style>
""", unsafe_allow_html=True)

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SLOT_MINUTES = 10
TZ = ZoneInfo("Europe/Madrid")

st.markdown("""
<style>

/* Slider - zona seleccionada */
.stSlider [data-baseweb="slider"] > div > div:nth-child(2) {
    background-color: #9aa3ad !important;
}

/* Slider - puntos/handles */
.stSlider [role="slider"] {
    background-color: #9aa3ad !important;
    border-color: #9aa3ad !important;
    box-shadow: none !important;
}

/* Slider - etiquetas de valores para distancia y rango horario */
.stSlider [data-testid="stThumbValue"] {
    color: #1f2933 !important;
    background-color: transparent !important;
    font-size: 16px !important;
    font-weight: 600 !important;
}

/* Reducir separación */
div[data-testid="column"] {
    padding-left: 0.10rem !important;
    padding-right: 0.10rem !important;
}

</style>
""", unsafe_allow_html=True)

def redondear_hora_actual():
    ahora = datetime.now(TZ)

    minutos_redondeados = ((ahora.minute + SLOT_MINUTES - 1) // SLOT_MINUTES) * SLOT_MINUTES

    hora_redondeada = ahora.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minutos_redondeados)

    hora_min = ahora.replace(hour=7, minute=0, second=0, microsecond=0)
    hora_max = ahora.replace(hour=20, minute=0, second=0, microsecond=0)

    if hora_redondeada < hora_min:
        hora_redondeada = hora_min

    if hora_redondeada > hora_max:
        hora_redondeada = hora_max

    return hora_redondeada.time()

if "jugadores" not in st.session_state:
    st.session_state.jugadores = None

if "hoyos_seleccionados" not in st.session_state:
    st.session_state.hoyos_seleccionados = ["18", "9"]

if "tipo_seleccionado" not in st.session_state:
    st.session_state.tipo_seleccionado = ["largo", "corto"]

def obtener_fecha_horas_default():
    ahora = datetime.now(TZ)

    if ahora.hour >= 18:
        fecha_default = ahora.date() + timedelta(days=1)
        hora_inicio_default = time(8, 0)
    else:
        fecha_default = ahora.date()
        hora_inicio_default = redondear_hora_actual()

    hora_fin_default_dt = datetime.combine(fecha_default, hora_inicio_default) + timedelta(hours=1)
    hora_fin_default = min(hora_fin_default_dt.time(), time(20, 0))

    return fecha_default, hora_inicio_default, hora_fin_default

fecha_default, hora_inicio_default, hora_fin_default = obtener_fecha_horas_default()

with st.container(border=True):
    st.markdown("""
    <div class="search-title">
        Busca tu próxima salida
    </div>
    """, unsafe_allow_html=True)

    localidades = cargar_localidades()

    lista_localidades = [
        f"{l['localidad']} ({l['provincia']})"
        for l in localidades
    ]

    col_localidad, col_zona = st.columns([2, 1])

    with col_localidad:
        localidad_seleccionada = st.selectbox(
            "📍 Buscar alrededor de",
            options=lista_localidades,
            index=None,
            placeholder="Selecciona una localidad"
        )

    zona_seleccionada = None
    localidad_obj_previa = None

    if localidad_seleccionada is not None:
        localidad_obj_previa = next(
            l for l in localidades
            if f"{l['localidad']} ({l['provincia']})" == localidad_seleccionada
        )

    with col_zona:
        if localidad_obj_previa and "zonas" in localidad_obj_previa:
            nombres_zonas = [z["zona"] for z in localidad_obj_previa["zonas"]]

            zona_seleccionada = st.selectbox(
                "Zona / Distrito",
                options=nombres_zonas,
                index=0
            )
        else:
            st.empty()

    radio_km = st.slider(
        "Radio de búsqueda (km)",
        min_value=0,
        max_value=100,
        value=10,
        step=10,
        key="radio_busqueda_km_v2"
    )

    col1, col2 = st.columns([1, 2])

    with col1:
        fecha = st.date_input(
            "Fecha",
            value=fecha_default,
            min_value=date.today(),
            format="DD/MM/YYYY"
        )

    with col2:
        hora_inicio, hora_fin = st.slider(
            "Franja horaria",
            min_value=time(7, 0),
            max_value=time(20, 0),
            value=(hora_inicio_default, hora_fin_default),
            step=timedelta(minutes=SLOT_MINUTES),
            format="HH:mm"
        )

    col3, col4, col5 = st.columns([1.4, 1, 1])

    with col3:
        jugadores_tmp = st.segmented_control(
            "Jugadores",
            options=[1, 2, 3, 4],
            format_func=lambda x: f"🏌️ x {x}",
            default=4,
            selection_mode="single",
            key="jugadores_segmented"
        )
        
        jugadores = jugadores_tmp

    with col4:
        hoyos_tmp = st.segmented_control(
            "Hoyos",
            options=["18", "9"],
            default=st.session_state.hoyos_seleccionados,
            selection_mode="multi",
            key="hoyos_segmented"
        )
    
        if set(hoyos_tmp) == {"18", "9"}:
            filtro_hoyos = "todos"
        elif hoyos_tmp == ["18"]:
            filtro_hoyos = "18"
        elif hoyos_tmp == ["9"]:
            filtro_hoyos = "9"
        else:
            filtro_hoyos = None

    with col5:
        tipo_tmp = st.segmented_control(
            "Tipo campo",
            options=["largo", "corto"],
            format_func=lambda x: x.capitalize(),
            default=st.session_state.tipo_seleccionado,
            selection_mode="multi",
            key="tipo_segmented"
        )
    
        if set(tipo_tmp) == {"largo", "corto"}:
            filtro_tipo = "todos"
        elif tipo_tmp == ["largo"]:
            filtro_tipo = "largo"
        elif tipo_tmp == ["corto"]:
            filtro_tipo = "corto"
        else:
            filtro_tipo = None

    hora_inicio_txt = hora_inicio.strftime("%H:%M")
    hora_fin_txt = hora_fin.strftime("%H:%M")

    campos_seleccionados_debug = None
    mostrar_payloads_debug = False
    mostrar_responses_debug = False
    mostrar_filtros_distancias_debug = False
    mostrar_editor_cache_distancias_debug = False

    if modo_debug:
        campos_debug = cargar_campos(solo_activos=False)
        nombres_campos_debug = sorted([nombre_campo(campo) for campo in campos_debug])

        st.markdown("### 🧪 Debug")

        campos_seleccionados_debug = st.multiselect(
            "Campos a consultar",
            options=nombres_campos_debug,
            default=[]
        )

        mostrar_payloads_debug = st.checkbox("Mostrar payloads enviados", value=False)
        mostrar_responses_debug = st.checkbox("Mostrar responses recibidas", value=False)
        mostrar_filtros_distancias_debug = st.checkbox("Mostrar filtros y distancias", value=False)
        mostrar_editor_cache_distancias_debug = st.checkbox("Mostrar editor caché distancias", value=False)

if "resultados_busqueda" not in st.session_state:
    st.session_state.resultados_busqueda = []

if "campos_no_consultables_busqueda" not in st.session_state:
    st.session_state.campos_no_consultables_busqueda = []

if "busqueda_realizada" not in st.session_state:
    st.session_state.busqueda_realizada = False

if st.button("Buscar", type="primary"):
        
    if modo_debug:
        st.session_state.debug_payloads = []
        st.session_state.debug_responses = []
        st.session_state.debug_filtros_distancias = []
        
    if localidad_seleccionada is None:
        st.error("Debes seleccionar una localidad.")
        st.stop()

    localidad_obj = next(
        l for l in localidades
        if f"{l['localidad']} ({l['provincia']})" == localidad_seleccionada
    )

    if "zonas" in localidad_obj:
        if zona_seleccionada is None:
            st.error("Debes seleccionar una zona/distrito.")
            st.stop()

        zona_obj = next(
            z for z in localidad_obj["zonas"]
            if z["zona"] == zona_seleccionada
        )

        lat_ref = zona_obj["lat"]
        lon_ref = zona_obj["lon"]
        zona_id = zona_obj.get("zona_id")
    else:
        lat_ref = localidad_obj["lat"]
        lon_ref = localidad_obj["lon"]
        zona_id = None

    localidad_id = localidad_obj.get("localidad_id")

    origen_cache = {
        "localidad_id": localidad_id,
        "municipio_id": localidad_obj.get("municipio_id"),
        "municipio_id_db": localidad_obj.get("municipio_id"),
        "zona_id": zona_id,
        "zona_id_db": zona_id,
        "municipio_ds": localidad_obj.get("municipio_ds") or localidad_obj.get("localidad"),
        "provincia_id": localidad_obj.get("provincia_id"),
        "provincia_ds": localidad_obj.get("provincia_ds") or localidad_obj.get("provincia"),
        "zona_ds": zona_obj.get("zona_ds") if "zonas" in localidad_obj else None,
        "lat": lat_ref,
        "lon": lon_ref
    }

    if jugadores is None or filtro_hoyos is None or filtro_tipo is None:
        st.error("Falta algún campo de búsqueda por seleccionar")
        st.stop()
    try:
        fecha_api = fecha.strftime("%Y/%m/%d")
        hora_inicio_api = datetime.strptime(hora_inicio_txt, "%H:%M").strftime("%H:%M")
        hora_fin_api = datetime.strptime(hora_fin_txt, "%H:%M").strftime("%H:%M")
    except ValueError:
        st.error("Revisa el formato de las horas. Deben estar en formato HH:MM.")
        st.stop()

    if hora_fin_api <= hora_inicio_api:
        st.error("La hora fin debe ser posterior a la hora inicio.")
        st.stop()
           
    resultados, campos_no_consultables = buscar_teetimes(
        fecha_api,
        hora_inicio_api,
        hora_fin_api,
        jugadores,
        filtro_hoyos,
        filtro_tipo,
        campos_seleccionados_debug,
        lat_ref,
        lon_ref,
        radio_km,
        origen_cache
    )

    st.session_state.resultados_busqueda = resultados
    st.session_state.campos_no_consultables_busqueda = campos_no_consultables
    st.session_state.busqueda_realizada = True

if st.session_state.busqueda_realizada:
    resultados = st.session_state.resultados_busqueda
    campos_no_consultables = st.session_state.campos_no_consultables_busqueda

    if not resultados and not campos_no_consultables:
        st.warning("No se encontraron campos con esos criterios.")
    else:
        if resultados:
            st.markdown(
            f"<div class='result-summary'>Se encontraron {len(resultados)} salidas disponibles.</div>",
            unsafe_allow_html=True
            )

            for i in range(0, len(resultados), 4):
                columnas = st.columns(4)

                for pos, (col, r) in enumerate(zip(columnas, resultados[i:i+4])):
                    idx_resultado = i + pos
                    tarifas_html = ""

                    for t in r["tarifas"]:
                        tarifas_html += f"<div class='tarifa'>• {t['nombre']}: <b>{t['precio']} €</b></div>"

                    with col:
                        titulo_campo = r['campo']
                        if modo_debug:
                            titulo_campo = "🧪 " + titulo_campo
                            
                        distancia_txt = ""
                        if r.get("distancia_km") is not None:
                            distancia_txt = f"📍 {round(r['distancia_km'],1)} km"
                            
                        st.markdown(f"""
                        <div class="result-card">
                            <div class="result-title">{titulo_campo}</div>
                            <div class="result-meta">{distancia_txt} · 🕒 <b>{r['hora']}</b> · 🏌️ x {r['jugadores_disponibles']}</div>
                            <div class="result-recorrido">{r['recorrido']}</div>
                            <hr class="card-separator">
                            <div class="tarifas-title">Tarifas</div>
                            {tarifas_html}
                        </div>
                        """, unsafe_allow_html=True)
                    
                        if st.button("Info reservas", key=f"info_reservas_{idx_resultado}_{r.get('campo_id', 'sin_id')}_{r.get('hora', '')}", use_container_width=True, type="secondary"):
                            mostrar_dialogo_info_reservas(r)
        else:
            st.warning("No se encontraron salidas disponibles con esos criterios.")

        if campos_no_consultables:
            st.markdown(
                """
                <div class="other-fields-section">
                    <div class="other-fields-title">Otros campos en tu área</div>
                    <div class="other-fields-subtitle">Campos cercanos sin disponibilidad online pública</div>
                </div>
                """,
                unsafe_allow_html=True
            )

            for i in range(0, len(campos_no_consultables), 4):
                columnas = st.columns(4)

                for pos, (col, campo_nc) in enumerate(zip(columnas, campos_no_consultables[i:i+4])):
                    idx_campo = i + pos
                    with col:
                        titulo_campo = campo_nc["campo"]
                        if modo_debug:
                            titulo_campo = "🧪 " + titulo_campo

                        distancia_txt = ""
                        if campo_nc.get("distancia_km") is not None:
                            distancia_txt = f"📍 {round(campo_nc['distancia_km'], 1)} km"

                        st.markdown(f"""
                        <div class="other-field-card">
                            <div class="other-field-title">{titulo_campo}</div>
                            <div class="other-field-meta">{distancia_txt}</div>
                        </div>
                        """, unsafe_allow_html=True)

                        if st.button("Info del club", key=f"info_club_{idx_campo}_{campo_nc.get('campo_id', 'sin_id')}", use_container_width=True, type="tertiary"):
                            mostrar_dialogo_info_club(campo_nc)

if modo_debug:
    if mostrar_payloads_debug or mostrar_responses_debug or mostrar_filtros_distancias_debug:
        st.markdown("### 🧪 Trazas debug")

        if mostrar_filtros_distancias_debug:
            pintar_caja_debug_filtros_distancias(
                "Filtros y distancias",
                st.session_state.debug_filtros_distancias
            )

        if mostrar_payloads_debug:
            pintar_caja_debug("Payloads enviados", st.session_state.debug_payloads)

        if mostrar_responses_debug:
            pintar_caja_debug("Responses recibidas", st.session_state.debug_responses)

    if mostrar_editor_cache_distancias_debug:
        pintar_editor_cache_distancias()

st.markdown("------")

st.markdown(
    "<p style='text-align:center; font-size:12px; color:gray;'>v3.0 - BETA-DEV</p>",
    unsafe_allow_html=True
)

col1, col2, col3 = st.columns([1, 2, 1])

with col2:
    st.markdown(
        "<div style='text-align:center;'>"
        "<img src='data:image/png;base64,{}' width='400'>"
        "</div>".format(
            base64.b64encode(open("powered.png", "rb").read()).decode()
        ),
        unsafe_allow_html=True
    )
    st.markdown(
    """
    <div class="footer-contact">
        ¿Tienes sugerencias o has encontrado algún problema?<br>
        📧 <a href="mailto:teeradar.es@gmail.com">
        teeradar.es@gmail.com
        </a>
    </div>
    """,
    unsafe_allow_html=True
    )
