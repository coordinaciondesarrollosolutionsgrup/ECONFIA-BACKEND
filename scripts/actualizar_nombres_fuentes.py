"""
Script para actualizar los nombres de las fuentes en la base de datos.
Mapea nombres técnicos a nombres oficiales/legibles.
"""

import os
import sys
import django
from core.models import Fuente

# Configurar Django
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from core.models import Fuente

# Mapeo de nombres técnicos a nombres oficiales
NOMBRES_FUENTES = {
    # Superintendencias y entidades de control Colombia
    'superfinanciera_busqueda': 'Superintendencia Financiera de Colombia',
    'superfinanciera_busqueda_pdf': 'Superintendencia Financiera de Colombia',
    'supersociedades_boletines': 'Superintendencia de Sociedades',
    'supersociedades_boletines_conceptos': 'Superintendencia de Sociedades - Boletines y Conceptos',
    'supersolidaria_noticias': 'Superintendencia de Economía Solidaria',
    
    # Procuraduría y entidades judiciales
    'procuraduria': 'Procuraduría General de la Nación',
    'procuraduria_certificado': 'Procuraduría General de la Nación - Certificado',
    'procuraduria_generar_certificado': 'Procuraduría General de la Nación - Certificado',
    'boletin_procuraduria': 'Boletín Procuraduría General de la Nación',
    
    # Policía Nacional
    'policia_nacional': 'Policía Nacional de Colombia',
    'policia_busqueda_general': 'Policía Nacional - Búsqueda General',
    'policia_busqueda_general_pdf': 'Policía Nacional - Búsqueda General',
    'policia_memorial_search': 'Policía Nacional - Memorial',
    'policia_memorial_search_pdf': 'Policía Nacional - Memorial',
    'boletin_policia': 'Boletín Policía Nacional',
    'mas_buscados_policia_colombia': 'Policía Nacional - Más Buscados',
    'mediacion_policia': 'Policía Nacional - Mediación',
    
    # Fiscalía y justicia
    'boletin_fiscalia': 'Fiscalía General de la Nación - Boletín',
    
    # Contraloría y entidades fiscales
    'contraloria': 'Contraloría General de la República',
    'antecedentes_fiscales': 'Antecedentes Fiscales',
    
    # DIAN y tributarias
    'dian_formalizacion_personas': 'DIAN - Formalización de Personas',
    
    # Rama Judicial
    'rama_judicial': 'Rama Judicial de Colombia',
    'rama_vigencias_pdf': 'Rama Judicial - Vigencias',
    'rama_abogado_certificado': 'Rama Judicial - Certificado de Abogado',
    'ramajudicial_consejo_estado_magistrados': 'Consejo de Estado - Magistrados',
    'ramajudicial_corte_constitucional_magistrados': 'Corte Constitucional - Magistrados',
    'ramajudicial_corte_constitucional_magistrados_anteriores': 'Corte Constitucional - Magistrados Anteriores',
    'ramajudicial_juzgados': 'Rama Judicial - Juzgados',
    
    # Registros y certificaciones Colombia
    'registro_civil': 'Registro Civil',
    'registraduria': 'Registraduría Nacional del Estado Civil',
    'rues': 'RUES - Registro Único Empresarial y Social',
    'runt': 'RUNT - Registro Único Nacional de Tránsito',
    'ruaf': 'RUAF - Registro Único de Afiliados',
    'rnmc': 'RNMC - Registro Nacional de Medidas Correctivas',
    'rethus': 'RETHUS - Registro Único Nacional del Talento Humano en Salud',
    'rethus_identificacion': 'RETHUS - Identificación',
    'repet': 'REPET - Registro Público de Espectáculos Públicos',
    
    # INPEC y sistema penitenciario
    'inpec': 'INPEC - Instituto Nacional Penitenciario y Carcelario',
    
    # SIMIT y tránsito
    'simit': 'SIMIT - Sistema Integrado de Información sobre Multas y Sanciones',
    'movilidad_bogota': 'Secretaría Distrital de Movilidad de Bogotá',
    'bicibogota': 'Sistema de Bicicletas Públicas de Bogotá',
    'adres_transito': 'ADRES - Tránsito',
    'adres': 'ADRES - Administradora de los Recursos del Sistema General de Seguridad Social en Salud',
    
    # Salud y afiliaciones
    'afiliados_eps': 'Afiliados EPS',
    'sisben': 'SISBEN - Sistema de Identificación de Potenciales Beneficiarios',
    'colpensiones_rpm': 'Colpensiones - Régimen de Prima Media',
    'porvenir_cert_afiliacion': 'Porvenir - Certificado de Afiliación',
    'tyba': 'Tyba',
    'skandia_enviar_certificado': 'Skandia - Certificado',
    
    # Educación
    'icfes': 'ICFES - Instituto Colombiano para la Evaluación de la Educación',
    'pruebas_icfes': 'ICFES - Pruebas',
    'certificado_sena': 'SENA - Certificado',
    'certificado_sena_sofia': 'SENA Sofía Plus - Certificado',
    
    # Defensa y militar
    'libreta_militar': 'Libreta Militar',
    'cgfm_mas_buscados': 'Cuerpo de Granaderos y Fusileros de Marina - Más Buscados',
    
    # Transparencia y contratación
    'colombiacompra_procesos': 'Colombia Compra Eficiente - Procesos',
    'colombiacompra_boletin_digital': 'Colombia Compra Eficiente - Boletín Digital',
    'secop_consulta_aacs': 'SECOP - Consulta AACS',
    'portal_transparencia_busca': 'Portal de Transparencia',
    'portal_transparencia_ceis': 'Portal de Transparencia - CEIS',
    'portal_transparencia_cepim': 'Portal de Transparencia - CEPIM',
    'portal_transparencia_leniencia': 'Portal de Transparencia - Leniencia',
    'bancoproveedores_quien_consulto': 'Banco de Proveedores - Quién Consultó',
    
    # UGPP
    'ugpp': 'UGPP - Unidad de Gestión Pensional y Parafiscales',
    
    # Garantías
    'garantias_mobiliarias_oficial': 'Garantías Mobiliarias',
    'garantias_mobiliarias_nooficial': 'Garantías Mobiliarias',
    
    # Consejos profesionales
    'cpnaa_certificado_vigencia': 'Consejo Profesional Nacional de Arquitectura - Certificado de Vigencia',
    'cpnaa_matricula_arquitecto': 'Consejo Profesional Nacional de Arquitectura - Matrícula',
    'cpae_certificado': 'Consejo Profesional de Administración de Empresas',
    'cpae_verify_certification': 'Consejo Profesional de Administración de Empresas - Certificación',
    'cpae_verify_licensure': 'Consejo Profesional de Administración de Empresas - Licencia',
    'cpaa_generar_certificado': 'Consejo Profesional de Agronomía - Certificado',
    'cpip_verif_matricula': 'Consejo Profesional de Ingeniería de Petróleos - Matrícula',
    'cpiq_certificado_vigencia': 'Consejo Profesional de Química - Certificado de Vigencia',
    'cpiq_validacion_certificado_vigencia': 'Consejo Profesional de Química - Validación Certificado',
    'cpiq_validacion_matricula': 'Consejo Profesional de Química - Validación Matrícula',
    'cpiq_validacion_tarjeta': 'Consejo Profesional de Química - Validación Tarjeta',
    'cpnt_consulta_licencia': 'Consejo Profesional Nacional de Topografía - Licencia',
    'cpnt_vigenciapdf': 'Consejo Profesional Nacional de Topografía - Vigencia',
    'cpnt_vigencia_externa_form': 'Consejo Profesional Nacional de Topografía - Vigencia Externa',
    'cpqcol_antecedentes': 'Colegio Químico Farmacéutico Colombiano - Antecedentes',
    'cpqcol_verificar': 'Colegio Químico Farmacéutico Colombiano - Verificación',
    'cp_certificado_busqueda': 'Consejo Profesional - Certificado',
    'cp_validar_certificado': 'Consejo Profesional - Validar Certificado',
    'cp_validar_matricula': 'Consejo Profesional - Validar Matrícula',
    'colpsic_validar_documento': 'Colegio Colombiano de Psicólogos - Validar Documento',
    'colpsic_verificacion_tarjetas': 'Colegio Colombiano de Psicólogos - Verificación Tarjetas',
    'conalpe_certificado': 'Consejo Nacional de Lenguas Extranjeras - Certificado',
    'conalpe_consulta_inscritos': 'Consejo Nacional de Lenguas Extranjeras - Inscritos',
    'conaltel_consulta_matriculados': 'Consejo Nacional de Tecnólogos Electricistas - Matriculados',
    'conpucol_certificados': 'Consejo Publicitario Colombiano - Certificados',
    'conpucol_verificacion_colegiados': 'Consejo Publicitario Colombiano - Colegiados',
    'conte_consulta_matricula': 'Consejo Profesional de Trabajo Social - Matrícula',
    'conte_consulta_vigencia': 'Consejo Profesional de Trabajo Social - Vigencia',
    'copnia_certificado': 'COPNIA - Consejo Profesional Nacional de Ingeniería y sus Profesiones Auxiliares',
    'cnb_carnet_afiliacion': 'Consejo Nacional de Bacteriología - Carnet de Afiliación',
    'cnb_consulta_matriculados': 'Consejo Nacional de Bacteriología - Matriculados',
    'colelectro_directorio': 'Colegio de Tecnólogos Electricistas y Electrónicos - Directorio',
    'ccap_validate_identity': 'CCAP - Validación de Identidad',
    'biologia_consulta': 'Consejo Profesional de Biología - Consulta',
    'biologia_validacion_certificados': 'Consejo Profesional de Biología - Validación Certificados',
    'tnem_certificados': 'TNEM - Certificados',
    
    # Ministerios Colombia
    'mincit': 'Ministerio de Comercio, Industria y Turismo',
    'mintransporte_capacitaciones': 'Ministerio de Transporte - Capacitaciones',
    'mindev': 'Ministerio de Desarrollo',
    
    # Gobierno y votación
    'cne_magistrados_busqueda_pdf': 'Consejo Nacional Electoral - Magistrados',
    'presidencia_gabinete_busqueda': 'Presidencia de la República - Gabinete',
    'sigep2_directorio': 'SIGEP - Sistema de Información y Gestión del Empleo Público',
    'eris': 'ERIS - Sistema de Información',
    'jurados_votacion': 'Jurados de Votación',
    'lugar_votacion': 'Lugar de Votación',
    
    # Personería y defunciones
    'personeria': 'Personería',
    'defunciones': 'Registro de Defunciones',
    'estado_cedula': 'Estado de Cédula',
    
    # SAMM
    'samm': 'SAMM - Sistema de Administración del Riesgo de Lavado de Activos',
    'samm_rcg': 'SAMM - Registro Central de Giros',
    'samm_policy_memo': 'SAMM - Memorando de Política',
    
    # Medicamentos y salud
    'medicaldevices': 'Dispositivos Médicos',
    'consulta_mediacion': 'Consulta de Mediación',
    'medidas_correctivas': 'Medidas Correctivas',
    'paco_contratista': 'PACO - Plan Anticorrupción y de Atención al Ciudadano',
    'sideap_comprobante': 'SIDEAP - Comprobante',
    'sirna_inscritos_png': 'SIRNA - Registro Nacional de Automotores - Inscritos',
    'sirna_sanciones_png': 'SIRNA - Registro Nacional de Automotores - Sanciones',
    'comprobador_derechos': 'Comprobador de Derechos',
    'compliance': 'Compliance',
    'inhabilidades': 'Registro de Inhabilidades',
    
    # Listas internacionales - OFAC
    'ofac_treas': 'OFAC - Office of Foreign Assets Control (US Treasury)',
    'ofac_treas_gov_pdf': 'OFAC - Office of Foreign Assets Control',
    'ofac_search_pdf': 'OFAC - Búsqueda',
    'ofac_programs_site_search_pdf': 'OFAC - Programas',
    'opensanctions_us_ofac_sdn': 'OpenSanctions - OFAC SDN',
    'opensanctions_us_ofac_cons': 'OpenSanctions - OFAC Consolidated',
    'opensanctions_us_ofac_cons_pdf': 'OpenSanctions - OFAC Consolidated',
    
    # FBI y agencias US
    'fbi': 'FBI - Federal Bureau of Investigation',
    'fbi_news': 'FBI - Noticias',
    'dea': 'DEA - Drug Enforcement Administration',
    'usa_drug': 'DEA - Lista de Drogas',
    'atf_noticias': 'ATF - Bureau of Alcohol, Tobacco, Firearms and Explosives - Noticias',
    'atf_recompensas': 'ATF - Recompensas',
    'ice_most_wanted_pdf': 'ICE - Immigration and Customs Enforcement - Más Buscados',
    'dhs_search': 'DHS - Department of Homeland Security',
    'secretservice_mostwanted': 'US Secret Service - Más Buscados',
    'secretservice_mostwanted_pdf': 'US Secret Service - Más Buscados',
    'epa_fugitives_search_pdf': 'EPA - Environmental Protection Agency - Fugitivos',
    
    # Department of State
    'departament_state': 'US Department of State',
    'departament_state2': 'US Department of State',
    'departament_state_2': 'US Department of State',
    'state_terrorist_orgs': 'US Department of State - Organizaciones Terroristas',
    'state_designation_cartels': 'US Department of State - Cárteles Designados',
    'state_designation_cartels_pdf': 'US Department of State - Cárteles Designados',
    'state_section_353': 'US Department of State - Sección 353',
    'state_section_353_pdf': 'US Department of State - Sección 353',
    'state_dss_mostwanted': 'US Department of State DSS - Más Buscados',
    'state_dss_mostwanted_pdf': 'US Department of State DSS - Más Buscados',
    
    # Department of Justice
    'departament_justice': 'US Department of Justice',
    'doj_fcpa_search_pdf': 'US DOJ - FCPA',
    
    # BIS - Commerce
    'bis_dpl_legacy_pdf': 'BIS - Denied Persons List',
    'bis_unverified_pdf': 'BIS - Unverified List',
    'opensanctions_bis_denied': 'OpenSanctions - BIS Denied',
    'opensanctions_us_bis_denied': 'OpenSanctions - BIS Denied Persons',
    
    # DDTC
    'opensanctions_us_ddtc': 'OpenSanctions - DDTC Debarred',
    'opensanctions_us_ddtc_debarred': 'OpenSanctions - DDTC Debarred',
    
    # Otras agencias US
    'opensanctions_us_cuba': 'OpenSanctions - Cuba Restricted List',
    'opensanctions_us_occ_enfact': 'OpenSanctions - OCC Enforcement Actions',
    'ecfr_part744_appendix_pdf': 'eCFR - Part 744 Appendix',
    'ecfr_search_pdf': 'eCFR - Electronic Code of Federal Regulations',
    'eo_13224_findit': 'Executive Order 13224',
    
    # UK - OFSI
    'ofsi_sanctions': 'OFSI - Office of Financial Sanctions Implementation (UK)',
    'ofsi_sanctions_pdf': 'OFSI - Office of Financial Sanctions Implementation (UK)',
    'ofsi_ukraine_govuk': 'OFSI - UK Sanciones Ucrania',
    'ofsi_consolidated_html': 'OFSI - Lista Consolidada',
    'ofsi_conlist_html': 'OFSI - Lista Consolidada',
    'ofsi_govuk': 'OFSI - Gov UK',
    'govuk_article_exactname': 'Gov UK - Búsqueda por Nombre',
    
    # Canadá
    'canada_sema_search_png': 'Canada SEMA - Special Economic Measures Act',
    'osfi_search': 'OSFI - Office of the Superintendent of Financial Institutions (Canada)',
    'osfi_search_pdf': 'OSFI - Office of the Superintendent of Financial Institutions (Canada)',
    'royal_canadian_mounted_police': 'RCMP - Royal Canadian Mounted Police',
    
    # Australia
    'opensanctions_au_dfat': 'OpenSanctions - Australia DFAT',
    'opensanctions_au_dfat_search': 'OpenSanctions - Australia DFAT',
    'dfat_consolidated_pdf': 'DFAT - Department of Foreign Affairs and Trade (Australia)',
    
    # Unión Europea
    'eu_fin_sanctions': 'Unión Europea - Sanciones Financieras',
    'eu_travelbans_pdf': 'Unión Europea - Prohibiciones de Viaje',
    'eu_travelban_pdf': 'Unión Europea - Prohibición de Viaje',
    'eu_most_wanted_pdf': 'Unión Europea - Más Buscados',
    'eu_sanctions_tracker': 'Unión Europea - Seguimiento de Sanciones',
    'eeas': 'EEAS - European External Action Service',
    'eur_lex_2014_833': 'EUR-Lex 2014/833',
    'eur_lex_2022_398': 'EUR-Lex 2022/398',
    'eur_lex_2022_399': 'EUR-Lex 2022/399',
    'eu_taric': 'EU TARIC',
    'opensanctions_eu_fsf': 'OpenSanctions - EU FSF',
    'opensanctions_nl_terrorism': 'OpenSanctions - Países Bajos Terrorismo',
    'opensanctions_be_fod': 'OpenSanctions - Bélgica FOD',
    
    # Francia
    'dgtresor_gels': 'Direction Générale du Trésor (Francia) - Congelamiento de Activos',
    
    # Luxemburgo
    'cssf': 'CSSF - Commission de Surveillance du Secteur Financier (Luxemburgo)',
    
    # Polonia
    'opensanctions_pl_mswia': 'OpenSanctions - Polonia MSWiA',
    
    # Suiza
    'opensanctions_seco': 'OpenSanctions - SECO (Suiza)',
    
    # Japón
    'opensanctions_jp_meti_eul': 'OpenSanctions - Japón METI',
    
    # Tailandia
    'opensanctions_th_designated_person': 'OpenSanctions - Tailandia Personas Designadas',
    
    # Azerbaiyán
    'opensanctions_az_fiu': 'OpenSanctions - Azerbaiyán FIU',
    
    # Palestina
    'opensanctions_ps_local_freezing': 'OpenSanctions - Palestina Congelamiento Local',
    
    # Sudáfrica
    'opensanctions_za_fic': 'OpenSanctions - Sudáfrica FIC',
    
    # Qatar
    'moci_qatar_search': 'Ministry of Commerce and Industry (Qatar)',
    
    # Bahréin
    'mofa_bh_cte': 'Ministry of Foreign Affairs (Bahréin) - Counter-Terrorism',
    
    # Alemania
    'embajada_alemania_funcionarios': 'Embajada de Alemania - Funcionarios',
    'guardia_civil_buscados_pdf': 'Guardia Civil (España) - Buscados',
    
    # UK NCA
    'nca_most_wanted_pdf': 'NCA - National Crime Agency (UK) - Más Buscados',
    
    # Nevis
    'nevis_fsrc': 'Nevis Financial Services Regulatory Commission',
    'nevis_fsrc_pdf_search': 'Nevis Financial Services Regulatory Commission',
    
    # Home Affairs
    'homeaffairs_search': 'Home Affairs - Búsqueda',
    'mha_individual_terrorists': 'Ministry of Home Affairs - Terroristas Individuales',
    'mha_individual_terrorists_pdf': 'Ministry of Home Affairs - Terroristas Individuales',
    
    # Interpol
    'interpol': 'INTERPOL',
    'interpol_red_notices': 'INTERPOL - Notificaciones Rojas',
    
    # ONU
    'un_sc_consolidated': 'ONU - Consejo de Seguridad Lista Consolidada',
    'un_consolidated_list': 'ONU - Lista Consolidada',
    'consolidated_list_onu': 'ONU - Lista Consolidada',
    
    # Bancos de desarrollo y organizaciones internacionales
    'worldbank_debarred_pdf': 'Banco Mundial - Lista de Inhabilitados',
    'idb_sanctioned_png': 'BID - Banco Interamericano de Desarrollo - Sancionados',
    'idb_sanctioned_pdf': 'BID - Banco Interamericano de Desarrollo - Sancionados',
    'afdb': 'AfDB - African Development Bank - Sancionados',
    'adb_sanctions': 'ADB - Asian Development Bank - Sancionados',
    'ebrd': 'EBRD - European Bank for Reconstruction and Development',
    'opensanctions_ebrd_ineligible': 'OpenSanctions - EBRD Inelegibles',
    
    # APGML
    'apgml_search': 'APGML - Asia/Pacific Group on Money Laundering',
    
    # SCA
    'sca_search': 'SCA - Superintendencia de Compañías',
    
    # NBCTF
    'nbctf': 'NBCTF - National Business Crime Task Force',
    'nbctf_downloads': 'NBCTF - Descargas',
    
    # FAC
    'fac_busqueda_pdf': 'FAC - Fuerza Aérea Colombiana',
    
    # Insight Crime
    'insightcrime_search_pdf': 'InSight Crime',
        
    # Offshore Leaks
    'offshore': 'Offshore Leaks',
    'offshore_offshoreleaks': 'Offshore Leaks Database',
    'offshore_paradise': 'Paradise Papers',
    'offshore_panama': 'Panama Papers',
    'offshore_bahamas': 'Bahamas Leaks',
    'pandora_papers': 'Pandora Papers',
    
    # Sanctions Map
    'sanctions_map': 'Sanctions Map',
    
    # México
    'scj_mas_buscados_pdf': 'Suprema Corte de Justicia (México) - Más Buscados',
    
    # Wikipedia
    'wikipedia_busqueda': 'Wikipedia',
    
    # PDF y búsquedas genéricas
    'pdf_search_highlight': 'Búsqueda PDF con Resaltado',
    
    # Configs y plantillas (generalmente no se muestran)
    'bot_configs': 'Configuración de Bots',
    'bot_configs_contratista': 'Configuración de Bots - Contratista',
    'bots_status_report': 'Reporte de Estado de Bots',
    'plantilla': 'Plantilla',
    'urls': 'URLs',
}

def migrar_fuentes():
    for nombre_tecnico, nombre_oficial in NOMBRES_FUENTES.items():
        fuente, created = Fuente.objects.get_or_create(
            nombre=nombre_tecnico,
            defaults={'nombre_pila': nombre_oficial}
        )
        if not created and fuente.nombre_pila != nombre_oficial:
            fuente.nombre_pila = nombre_oficial
            fuente.save()
        print(f"{'Creada' if created else 'Actualizada'}: {nombre_tecnico} -> {nombre_oficial}")

def actualizar_nombres_fuentes(dry_run=True):
    """
    Actualiza el campo nombre_pila de las fuentes según el mapeo.
    
    Args:
        dry_run: Si es True, solo muestra los cambios sin aplicarlos
    """
    fuentes_actualizadas = 0
    fuentes_no_encontradas = []
    
    print(f"\n{'=' * 80}")
    print(f"{'MODO DRY RUN - SOLO VISTA PREVIA' if dry_run else 'MODO ACTUALIZACIÓN - APLICANDO CAMBIOS'}")
    print(f"{'=' * 80}\n")
    
    for nombre_tecnico, nombre_oficial in NOMBRES_FUENTES.items():
        try:
            fuente = Fuente.objects.get(nombre=nombre_tecnico)
            nombre_anterior = fuente.nombre_pila
            
            if nombre_anterior != nombre_oficial:
                print(f"✓ {nombre_tecnico}")
                print(f"  Anterior: {nombre_anterior}")
                print(f"  Nuevo:    {nombre_oficial}")
                print()
                
                if not dry_run:
                    fuente.nombre_pila = nombre_oficial
                    fuente.save()
                
                fuentes_actualizadas += 1
        except Fuente.DoesNotExist:
            fuentes_no_encontradas.append(nombre_tecnico)
    
    print(f"\n{'=' * 80}")
    print(f"RESUMEN:")
    print(f"  - Fuentes actualizadas: {fuentes_actualizadas}")
    print(f"  - Fuentes no encontradas en BD: {len(fuentes_no_encontradas)}")
    
    if fuentes_no_encontradas and len(fuentes_no_encontradas) <= 20:
        print(f"\nFuentes no encontradas:")
        for nombre in fuentes_no_encontradas:
            print(f"  - {nombre}")
    
    print(f"{'=' * 80}\n")
    
    return fuentes_actualizadas, fuentes_no_encontradas


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Actualizar nombres de fuentes')
    parser.add_argument('--apply', action='store_true', 
                       help='Aplicar cambios (por defecto solo muestra vista previa)')
    
    args = parser.parse_args()
    
    actualizar_nombres_fuentes(dry_run=not args.apply)
