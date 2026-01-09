
import os
import sys
import re
from pathlib import Path

# --- Ajuste robusto para encontrar la raíz del proyecto y el módulo backend ---
CURRENT = Path(__file__).resolve()
ROOT = CURRENT.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Si el módulo backend no se encuentra, intenta buscarlo dinámicamente
if not (ROOT / 'backend').is_dir():
    raise RuntimeError(f"No se encontró la carpeta 'backend' en {ROOT}")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django
from django.db import transaction, IntegrityError


# 1) Pega aquí tu tabla (las filas) tal cual: ID  slug  Nombre mostrado  Tipo
RAW = r"""
1	estado_cedula	Certificado de Estado de Cédula de Ciudadanía	Nacional
2	eu_taric	Unión Europea – TARIC (Arancel Integrado Comunitario)	Internacional
3	fac_busqueda_pdf	Fuerza Aérea Colombiana – Consultas y Publicacione	Nacional
4	fbi_news	FBI – Comunicados y Noticias Oficiales	Internacional
5	garantias_mobiliarias_nooficial	Registro de Garantías Mobiliarias – Consulta Informativa	Nacional
6	govuk_article_exactname	Gobierno del Reino Unido (GOV.UK) – Publicaciones Oficiales	Internacional
7	homeaffairs_search	Departamento de Asuntos Internos – Sudáfrica	Internacional
8	pruebas_icfes	ICFES – Resultados de Pruebas de Estado	Nacional
9	idb_sanctioned_png	Banco Interamericano de Desarrollo (BID) – Entidades Sancionadas	Nacional
10	inpec	INPEC – Instituto Nacional Penitenciario y Carcelario	Nacional
11	insightcrime_search_pdf	InSight Crime – Investigaciones sobre Crimen Organizado	Internacional
12	interpol_red_notices	INTERPOL – Notificaciones Rojas	Internacional
13	libreta_militar	Libreta Militar – Fuerzas Militares de Colombia	Nacional
14	consulta_mediacion	Centros de Conciliación y Mediación – Colombia	Nacional
15	contraloria	Contraloría General de la República de Colombia	Nacional
16	mfat_sanctions	Ministerio de Asuntos Exteriores de Japón – Lista de Sanciones	Internacional
17	mindev	Ministerio de Desarrollo Económico	Nacional
18	moci_qatar_search	Ministerio de Comercio e Industria de Catar – Búsqueda	Internacional
19	movilidad_bogota	Secretaría Distrital de Movilidad de Bogotá	Nacional
20	nbctf_downloads	Base Internacional contra el Financiamiento del Terrorismo (NBCTF)	Internacional
21	nevis_fsrc	Nevis – Comisión de Regulación de Servicios Financieros (FSRC)	Internacional
22	ebrd	Banco Europeo de Reconstrucción y Desarrollo (EBRD)	Internacional
23	eur_lex_2014_833	Unión Europea – Reglamento (UE) 2014/833	Internacional
24	eu_fin_sanctions	Unión Europea – Sanciones Financieras	Internacional
25	eu_travelbans_pdf	Unión Europea – Prohibiciones de Viaje (Travel Bans)	Internacional
26	interpol	INTERPOL – Organización Internacional de Policía Criminal	Internacional
27	mas_buscados_policia_colombia	Policía Nacional de Colombia – Personas Más Buscadas	Nacional
28	medicaldevices	Registros Internacionales de Dispositivos Médicos	Internacional
29	ofac_treas	Estados Unidos – OFAC – Departamento del Tesoro	Internacional
30	offshore_offshoreleaks	Offshore Leaks – Consorcio Internacional de Periodistas (ICIJ)	Internacional
31	offshore_paradise	Paradise Papers – Investigación Offshore	Internacional
32	ofsi_sanctions	Reino Unido – Lista General de Sanciones (OFSI)	Internacional
33	ofsi_ukraine_govuk	Reino Unido – Sanciones por Ucrania (Gov.UK)	Internacional
34	opensanctions_au_dfat	Australia – DFAT – Lista de Sanciones	Internacional
35	opensanctions_au_dfat_search	Australia – DFAT – Búsqueda de Sanciones	Internacional
36	opensanctions_ebrd_ineligible	Banco Europeo de Reconstrucción y Desarrollo – Entidades Inhabilitadas	Internacional
37	opensanctions_nl_terrorism	Países Bajos – Lista de Terrorismo	Internacional
38	opensanctions_ps_local_freezing	Autoridad Palestina – Congelamiento de Activos	Internacional
39	opensanctions_us_cuba	Estados Unidos – Sanciones relacionadas con Cuba	Internacional
40	opensanctions_us_occ_enfact	Estados Unidos – OCC – Medidas de Cumplimiento (Enforcement Actions)	Internacional
41	opensanctions_za_fic	Sudáfrica – Centro de Inteligencia Financiera (FIC)	Internacional
42	osfi_search	Reino Unido – OFSI (Oficina de Implementación de Sanciones Financieras	Internacional
43	pandora_papers	Pandora Papers – Investigación Periodística Internacional	Internacional
44	pdf_search_highlight	Búsqueda y Análisis de Documentos PDF (Fuentes Abiertas)	Internacional
45	policia_busqueda_general	Policía Nacional de Colombia – Búsqueda General	Nacional
46	portal_transparencia_cepim	Portal de Transparencia – Información de Personas y Entidades (CEPIM)	Nacional
47	presidencia_gabinete_busqueda	Presidencia de la República – Gabinete y Altos Funcionarios	Nacional
48	procuraduria_certificado	o Procuraduría General de la Nación – Certificado de Antecedentes	Nacional
49	rama_judicial	Rama Judicial de Colombia – Consulta General	Nacional
50	rethus	RETHUS – Registro Único Nacional del Talento Humano en Salud	Nacional
51	rnmc	RNMC – Registro Nacional de Medidas Correctivas	Nacional
52	rues	RUES – Registro Único Empresarial y Social	Nacional
53	samm	Estados Unidos – Metodología de Evaluación de Sanciones (SAMM)	Internacional
54	samm_rcg	Estados Unidos – Guías de Riesgo y Cumplimiento de Sanciones (SAMM-RCG)	Internacional
55	sca_search	Autoridad Federal de Competencia de los EAU – Búsqueda de Sanciones (SCA)	Internacional
56	scj_mas_buscados_pdf	Fiscalía / Rama Judicial – Personas Más Buscadas	Nacional
57	sideap_comprobante	SIDEAP – Comprobante de Vinculación al Estado	Nacional
58	simit	SIMIT – Sistema Integrado de Multas y Sanciones de Tránsito	Nacional
59	sisben	SISBÉN – Sistema de Identificación de Potenciales Beneficiarios	Nacional
60	state_designation_cartels	Departamento de Estado de EE. UU. – Designación de Cárteles	Internacional
61	state_dss_mostwanted	Departamento de Estado de EE. UU. – Más Buscados (DSS)	Internacional
62	superfinanciera_busqueda_pdf	Superintendencia Financiera de Colombia	Nacional
63	supersolidaria_noticias	Superintendencia de la Economía Solidaria – Noticias	Nacional
64	ugpp	UGPP – Unidad de Gestión Pensional y Parafiscales	Nacional
65	wikipedia_busqueda	Wikipedia – Búsqueda de Referencias Públicas	Internacional
66	usa_drug	Estados Unidos – Listas y Delitos de Drogas	Internacional
67	worldbank_debarred_pdf	Banco Mundial – Lista de Personas y Empresas Inhabilitadas	Internacional
68	un_sc_consolidated	Consejo de Seguridad de la ONU – Lista Consolidada	Internacional
69	consolidated_list_onu	ONU – Lista Consolidada de Sanciones	Internacional
70	tyba	TYBA – Consulta de Procesos Judiciales (Rama Judicial)	Nacional
71	supersociedades_boletines_conceptos	Superintendencia de Sociedades – Boletines y Conceptos	Nacional
72	tnem_certificados	TNEM – Certificados y Registros Administrativos	Nacional
73	state_terrorist_orgs	Estados Unidos – Organizaciones Terroristas Extranjeras (FTO)	Internacional
74	state_section_353	Estados Unidos – Sección 353 (Sanciones y Seguridad Nacional)	Internacional
75	sirna_sanciones_png	SIRNA – Abogados Sancionados	Colegio Regulador
76	sirna_inscritos_png	SIRNA – Registro Nacional de Abogados Inscritos	Nacional
77	sigep2_directorio	SIGEP II – Directorio de Servidores Públicos	Nacional
78	secretservice_mostwanted	Servicio Secreto de los Estados Unidos – Más Buscados	Internacional
79	secop_consulta_aacs	SECOP – Consulta de Acuerdos y Contratos Estatales	Internacional
80	sanctions_map	Mapa Global de Sanciones Internacionales	Internacional
81	samm_policy_memo	Estados Unidos – Memorandos de Política de Sanciones (SAMM)	Internacional
82	runt	RUNT – Registro Único Nacional de Tránsito	Nacional
83	ruaf	RUAF – Registro Único de Afiliados (Colombia)	Nacional
84	royal_canadian_mounted_police	Real Policía Montada de Canadá (RCMP)	Internacional
85	rethus_identificacion	RETHUS – Registro Único Nacional del Talento Humano en Salud	Nacional
86	repet	REPET – Registro de Personas y Entidades (Colombia)	Nacional
87	registro_civil	Registro Civil de Nacimiento, Matrimonio y Defunción – Colombia	Nacional
88	rama_vigencias_pdf	Rama Judicial – Certificados de Vigencia	Colegio Regulador
89	rama_abogado_certificado	Rama Judicial – Certificado de Abogado	Colegio Regulador
90	ramajudicial_corte_constitucional_magistrados_anteriores	Corte Constitucional de Colombia – Magistrados Anteriores	Nacional
91	ramajudicial_corte_constitucional_magistrados	Corte Constitucional de Colombia – Magistrados Vigentes	Nacional
92	procuraduria	Procuraduría General de la Nación	Nacional
93	porvenir_cert_afiliacion	Porvenir – Certificado de Afiliación	Nacional
94	portal_transparencia_leniencia	Portal de Transparencia – Programa de Clemencia / Leniencia	Nacional
95	portal_transparencia_ceis	Portal de Transparencia – Información Estratégica del Estado (CEIS)	Nacional
96	portal_transparencia_busca	Portal de Transparencia del Estado Colombiano – Búsqueda	Nacional
97	policia_memorial_search	Policía Nacional de Colombia – Memorial de Personas Buscadas	Nacional
98	policia_nacional	Policía Nacional de Colombia	Nacional
99	personeria	Personería Municipal – Colombia	Nacional
100	paco_contratista	Portal Anticorrupción de Colombia – Contratistas (PACO)	Nacional
101	opensanctions_us_ofac_sdn	Estados Unidos – OFAC – Lista SDN	Internacional
102	opensanctions_us_ofac_cons	Estados Unidos – OFAC – Lista Consolidada	Internacional
103	opensanctions_us_ddtc_debarred	Estados Unidos – DDTC – Personas Inhabilitadas	Internacional
104	opensanctions_us_bis_denied	Estados Unidos – BIS Denied Persons List	Internacional
105	opensanctions_th_designated_person	Tailandia – Personas Designadas por Sancione	Internacional
106	opensanctions_seco	Suiza – Secretaría de Estado para Asuntos Económicos (SECO)	Internacional
107	opensanctions_pl_mswia	Polonia – Ministerio del Interior y Administración	Internacional
108	opensanctions_jp_meti_eul	Japón – Ministerio de Economía, Comercio e Industria (METI)	Internacional
109	opensanctions_eu_fsf	Unión Europea – Lista de Sanciones Financieras	Internacional
110	opensanctions_bis_denied	Estados Unidos – BIS Denied Persons List	Internacional
111	opensanctions_be_fod	Estados Unidos – BIS Denied Persons List	Internacional
112	opensanctions_az_fiu	Azerbaiyán – Unidad de Inteligencia Financiera (FIU)	Internacional
113	ofsi_consolidated_html	Reino Unido – Oficina de Implementación de Sanciones Financieras (OFSI	Internacional
114	offshore_panama	Registros Offshore – Panamá (Panama Papers)	Internacional
115	offshore_bahamas	Registros Offshore – Bahamas	Internacional
116	nbctf	Base de Datos contra el Financiamiento del Terrorismo (NBCTF)	Internacional
117	jurados_votacion	Registraduría Nacional – Jurados de Votación	Nacional
118	lugar_votacion	Registraduría Nacional – Lugar de Votación	Nacional
119	inhabilidades	Registro de Inhabilidades y Sanciones	Nacional
120	departament_state2	Departamento de Estado de Estados Unidos (Alterna)	Internacional
121	departament_state	Departamento de Estado de Estados Unidos	Internacional
122	departament_justice	Departamento de Justicia de Estados Unidos	Internacional
123	defunciones	Registro Único de Defunciones – Colombia	Nacional
124	dea	Drug Enforcement Administration (USA)	Internacional
125	cssf	Comisión de Supervisión del Sector Financiero de Luxemburgo (CSSF)	Internacional
126	cp_validar_matricula	Consejo Profesional Nacional de Ingenierías Eléctrica, Mecánica y profesiones afines Matricula	Colegio Regulador
127	csl_search_pdf	Administración de Comercio Internacional	Internacional
128	cp_validar_certificado	Consejo Profesional Nacional de Ingenierías Eléctrica, Mecánica y profesiones afines	Colegio Regulador
129	cp_certificado_busqueda	Consejos Profesionales – Certificados y Verificación	Nacional
130	cpqcol_verificar	CPQCOL – Verificación Profesional	Colegio Regulador
131	cpnt_vigencia_externa_form	CPNT – Consulta Externa	Colegio Regulador
132	cpqcol_antecedentes	Consejo Profesional de Química	Colegio Regulador
133	cpnt_vigenciapdf	CPNT – Certificado de Vigencia	Colegio Regulador
134	cpnt_consulta_licencia	Consejo Profesional Nacional de Topografía	Colegio Regulador
135	cpnaa_matricula_arquitecto	CPNAA – Matrícula de Arquitectos	Colegio Regulador
136	cpnaa_certificado_vigencia	Consejo Profesional de Arquitectura y Urbanismo	Colegio Regulador
137	cpiq_validacion_tarjeta	CPIQ – Tarjeta Profesional	Colegio Regulador
138	cpiq_validacion_matricula	CPIQ – Matrícula Profesional	Colegio Regulador
139	cpiq_validacion_certificado_vigencia	CPIQ – Validación de Certificados	Colegio Regulador
140	cpiq_certificado_vigencia	Consejo Profesional de Ingeniería Química	Colegio Regulador
141	cpip_verif_matricula	Consejo Profesional de Ingeniería	Colegio Regulador
142	cpae_verify_licensure	CPAE – Licencias Profesionales	Colegio Regulador
143	cpae_verify_certification	CPAE – Verificación Profesional	Colegio Regulador
144	cpaa_generar_certificado	Consejo Profesional de Arquitectura	Colegio Regulador
145	copnia_certificado	COPNIA – Ingeniería y Profesiones Afines	Colegio Regulador
146	cpae_certificado	Consejo Profesional de Administración de Empresas	Colegio Regulador
147	conte_consulta_vigencia	CONTE – Vigencia de Matrícula	Colegio Regulador
148	conte_consulta_matricula	Consejo Técnico de Electricistas (CONTE)	Colegio Regulador
149	conpucol_certificados	CONPUCOL – Certificados Profesionales	Colegio Regulador
150	conaltel_consulta_matriculados	CONALTEL – Consulta de Matriculados	Colegio Regulador
151	conpucol_verificacion_colegiados	Consejo Profesional de la Comunicación	Colegio Regulador
152	conalpe_consulta_inscritos	CONALPE – Registro de Inscritos	Colegio Regulador
153	conalpe_certificado	Consejo Nacional de Licencias en Educación	Colegio Regulador
154	compliance	Listas de Cumplimiento y Riesgo (Compliance)	Internacional
155	comprobador_derechos	s Consulta de Derechos y Beneficios Sociales	Nacional
156	colpsic_verificacion_tarjetas	COLPSIC – Tarjeta Profesional	Colegio Regulador
157	colpsic_validar_documento	Colegio Colombiano de Psicólogos (COLPSIC)	Colegio Regulador
158	colombiacompra_procesos	SECOP – Procesos de Contratación	Nacional
159	colelectro_directorio	Colegio de Electromecánicos – Directorio Profesional	Colegio Regulador
160	colombiacompra_boletin_digital	Colombia Compra Eficiente	Nacional
161	colpensiones_rpm	Colpensiones – Régimen de Prima Media	Nacional
162	cne_magistrados_busqueda_pdf	Consejo Nacional Electoral – Magistrados	Nacional
163	cnb_consulta_matriculados	Colegio Nacional de Bacteriología – Consulta de Matriculados	Colegio Regulador
164	cgfm_mas_buscados	Fuerzas Militares de Colombia – Más Buscados	Internacional
165	cnb_carnet_afiliacion	Colegio Nacional de Bacteriología – Carné de Afiliación	Colegio Regulador
166	canada_sema_search_png	Gobierno de Canadá – Sanciones SEMA	Internacional
167	boletin_procuraduria	Procuraduría General de la Nación	Nacional
168	boletin_policia	Policía Nacional de Colombia	Nacional
169	boletin_fiscalia	Fiscalía General de la Nación	Nacional
170	bis_unverified_pdf	BIS – Unverified List (USA)	Internacional
171	bis_dpl_legacy_pdf	BIS – Denied Persons List (USA)	Internacional
172	biologia_validacion_certificados	Colegio de Biólogos – Validación de Certificados	Colegio Regulador
173	biologia_consulta	Registro Nacional de Biología – Consulta	Colegio Regulador
174	bicibogota	BiciBogotá – Sistema de Bicicletas Públicas	Nacional
175	banco_proveedores_consulta_estados	Banco de Proveedores – Historial de Consultas	Nacional
176	atf_recompensas	ATF – Avisos de Recompensa (EE. UU.)	Internacional
177	atf_noticias	ATF – Comunicados de Prensa (EE. UU.)	Internacional
178	apgml_search	Grupo Asia/Pacífico contra el Lavado de Dinero (APG)	Internacional
179	antecedentes_fiscales	Contraloría General – Antecedentes Fiscales	Nacional
180	afiliados_eps	Sistema General de Seguridad Social en Salud (EPS)	Nacional
181	afdb	Banco Africano de Desarrollo	Internacional
182	adres_transito	ADRES – Información de Tránsito	Nacional
183	adres	ADRES – Administradora de Recursos del Sistema de Salud	Nacional
184	adb_sanctions	Banco Asiático de Desarrollo	Internacional
185	skandia_enviar_certificado	skandia certificado afiliacion	Nacional
186	supersociedades_boletines	Superintendencia de Sociedades	Nacional
187	dfat_consolidated_pdf	Gobierno de Australia – Lista de Sancione	Internacional
188	dgtresor_gels	Ministerio de Economía y Finanzas – Francia	Internacional
189	dhs_search	Department of Homeland Security (USA)	Internacional
190	dian_formalizacion_personas	DIAN – Formalización de Personas	Nacional
191	doj_fcpa_search_pdf	Departamento de Justicia (USA) – FCPA	Internacional
192	ecfr_part744_appendix_pdf	EAR – Parte 744 Apéndices	Internacional
193	ecfr_search_pdf	EAR – Export Administration Regulations	Internacional
194	eeas	Servicio Europeo de Acción Exterior (UE)	Internacional
195	embajada_alemania_funcionarios	Embajada de Alemania – Funcionarios	Internacional
196	eo_13224_findit	Estados Unidos – Executive Order 13224 (Terrorismo)	Colegio Regulador
197	epa_fugitives_search_pdf	Agencia de Protección Ambiental (EPA – USA)	Internacional
198	eur_lex_2022_398	Unión Europea – EUR-LEX (Reglamento 2022/398	Internacional
199	eur_lex_2022_399	Unión Europea – EUR-LEX (Reglamento 2022/399	Internacional
200	juzgado_armenia_calarca	Juzgado Armenia – Calarcá	Nacional
201	juzgado_barranquilla	Juzgado de Barranquilla	Nacional
202	juzgado_bogota	Juzgado de Bogotá	Nacional
203	juzgado_bucaramanga	Juzgado de Bucaramanga	Nacional
204	juzgado_buga	Juzgado de Buga	Nacional
205	juzgado_cali	Juzgado de Cali	Nacional
206	juzgado_cartagena	juzgado de Cartagena	Nacional
207	juzgado_florencia	Juzgado de Florencia	Nacional
208	juzgado_ibague	Juzgado de Ibagué	Nacional
209	juzgado_la_dorada	Juzgado de La Dorada	Nacional
210	juzgado_manizales	Juzgado de Manizales	Nacional
211	juzgado_medellin	Juzgado de Medellín	Nacional
212	juzgado_monteria	Juzgado de Montería	Nacional
213	juzgado_neiva	Juzgado de Neiva	Nacional
214	juzgado_palmira	Juzgado de Palmira	Nacional
215	juzgado_pasto	Juzgado de Pasto	Nacional
216	juzgado_popayan	Juzgado de Popayán	Nacional
217	juzgado_quibdo	Juzgado de Quibdó	Nacional
218	juzgado_santa_marta	Juzgado de Santa Marta	Nacional
219	opensanctions_adb	OpenSanctions – Base de Personas y Entidades Sancionadas	Internacional
220	mofa_bh_cte	Ministerio de Relaciones Exteriores de Baréin – Lista de Terroristas	Internacional
221	dgtresor_gels_avoirs	Dirección General del Tesoro de Francia – Congelación de Activos	Internacional
222	mintransporte_capacitaciones	Ministerio de Transporte de Colombia – Registro de Capacitaciones	Nacional
223	mha_individual_terrorists	Ministerio del Interior de India – Lista de Terroristas Individuales	Internacional
224	garantias_mobiliarias_oficial	Registro de Garantías Mobiliarias de Colombia	Nacional
225	fbi	Federal Bureau of Investigation (FBI)	Internacional
226	eu_sanctions_tracker	Unión Europea – Rastreador de Sanciones	Internacional
227	eu_most_wanted_pdf	Europol – Lista de los Más Buscados en Europa	Internacional
228	autria_public_officials	Austria – Funcionarios Públicos	Internacional
229	canadian_listed_terrorist_entities	Canadá – Entidades Terroristas Designadas	Internacional
230	nepal_prohibited_persons_groups	Nepal – Personas o Grupos Prohibidos (Estrategia Nacional 2076–2081)	Internacional
231	colombian_pep_declarations	Colombia – Declaraciones de Personas Expuestas Políticamente (PEP)	Nacional
232	colombian_joining_the_dots_peps	Colombia – PEPs (Proyecto Joining the Dots)	Nacional
233	acf_list_of_war_enablers	ACF – Facilitadores de Conflictos Armados	Internacional
234	iran_sanctions_list	Irán – Lista de Sanciones	Internacional
235	china_sanctions_research	China – Investigación de Sanciones	Internacional
236	ukraine_sfms_blacklist	Ucrania – Lista Negra del Servicio de Monitoreo Financiero	Internacional
237	us_colorado_medicaid_terminated_providers	s EE. UU. Colorado – Proveedores Medicaid Excluidos	Internacional
238	us_oregon_medicaid_fraud_convictions	EE. UU. Oregón – Condenas por Fraude Medicaid	Internacional
239	us_pennsylvania_medicheck_list	EE. UU. Pensilvania – Lista Medicheck	Internacional
240	us_navy_leadership	EE. UU. – Liderazgo de la Marina	Internacional
241	us_mississippi_medicaid_terminated_providers	EE. UU. Misisipi – Proveedores Medicaid Excluidos	Internacional
242	us_missouri_medicaid_provider_terminations	EE. UU. Misuri – Terminaciones de Proveedores Medicaid	Internacional
243	us_maine_medicaid_excluded_providers	EE. UU. Maine – Proveedores Medicaid Excluidos	Internacional
244	us_maryland_sanctioned_providers	EE. UU. Maryland – Proveedores Sancionados	Internacional
245	us_federal_reserve_enforcement_actions	EE. UU. Reserva Federal – Acciones de Cumplimiento	Internacional
246	us_fincen_special_measures	EE. UU. FinCEN – Medidas Especiales (Secciones 311 y 9714)	Internacional
247	us_finra_enforcement_actions	EE. UU. FINRA – Acciones Disciplinarias	Internacional
248	us_georgia_healthcare_exclusions	EE. UU. Georgia – Exclusiones del Sector Salud	Internacional
249	us_hawaii_medicaid_exclusions_reinstatements	EE. UU. Hawái – Exclusiones y Reincorporaciones Medicaid	Internacional
250	us_hhs_inspector_general_exclusions	EE. UU. HHS – Exclusiones del Inspector General	Internacional
251	us_ice_most_wanted_fugitives	EE. UU. ICE – Fugitivos Más Buscados	Internacional
252	us_indiana_medicaid_terminated_providers	EE. UU. Indiana – Proveedores Medicaid Excluidos	Internacional
253	us_iowa_medicaid_terminated_providers	EE. UU. Iowa – Proveedores Medicaid Excluidos	Internacional
254	us_kansas_medicaid_terminated_providers	EE. UU. Kansas – Proveedores Medicaid Excluidos	Internacional
255	us_delaware_medicaid_sanctioned_providers	EE. UU. Delaware – Proveedores Medicaid Sancionados	Internacional
256	us_state_foreign_terrorist_organizations	EE. UU. Departamento de Estado – Organizaciones Terroristas Extranjeras	Internacional
257	us_state_terrorist_exclusion	EE. UU. Departamento de Estado – Exclusión por Terrorismo	Internacional
258	us_ddtc_aeca_debarments	EE. UU. DDTC – Inhabilitaciones por la Ley AECA	Internacional
259	us_ddtc_penalties_oversight_agreements	EE. UU. DDTC – Sanciones y Acuerdos de Supervisión	Internacional
260	us_dod_chinese_military_companies	EE. UU. DoD – Empresas Militares Chinas	Internacional
261	south_africa_wanted_persons	Sudáfrica – Personas Buscadas	Internacional
262	romania_fiu_public_officials	Rumania – Funcionarios Públicos (Unidad de Inteligencia Financiera)	Internacional
263	russia_pmc_wagner_mercenaries	Rusia – Mercenarios del Grupo Wagner	Internacional
264	brazil_debarred_bidders	Brasil – Oferentes Inhabilitados	Internacional
265	estonia_international_sanctions_act_list	Estonia – Lista según la Ley de Sanciones Internacionales	Internacional
266	venezuela_national_assembly_members	Venezuela – Miembros de la Asamblea Nacional	Internacional
267	asian_development_bank_sanctions	Banco Asiático de Desarrollo – Lista de Sanciones	Internacional
268	CNDJ_antecedentes_disciplinarios	CONSULTA DE SANCIONES VIGENTES PARA ABOGADOS	Colegio Regulador
269 policia_memorial_busqueda  Policia Nacional Memoria de Busqueda  Nacional
270 dispositivos_medico Registro de Dispositivos Medicos Nacional
271 banco_proveedores_quien_consulta Banco de Proveedores Quien Consulta  Nacional
272 samm_memorando_politica Estados Unidos  Memorandos de Politica de Sanciones  Internacional
273 cne_magistrados_busqueda Consejo Nacional Electoral  Magistrados  Nacional
274 eris Eris  Internacional
275 guardia_civil_buscados_pdf Guardia Civil de España  Mas Buscados  Internacional
276 medical_devices Registros Internacionales de Dispositivos Medicos  Internacional
277 ofsi_conlist_html Reino Unido  Oficina de Implementacion de Sanciones Financieras (OFSI  Internacional
278 ofsi_pdf OFSI Consolidated List Search Reino Unido  Internacional
279 policia_busqueda_general_shot Policia Nacional de Colombia  Busqueda General con Foto  Nacional
280 ramajudicial_consejo_estado_magistrados Consejo de Estado de Colombia  Magistrados Vigentes  Nacional
281 ramajudicial_juzgados Rama Judicial de Colombia  Juzgados  Nacional

"""


def _clean_nombre(nombre: str) -> str:
    # Limpia prefijos raros que aparecen al copiar (ej: "s EE. UU....", "o Procuraduría...")
    n = nombre.strip()
    if len(n) > 2 and n[1] == " " and n[0] in ("s", "o") and n[2].isupper():
        n = n[2:].lstrip()
    return n


def parse_rows(raw: str):
    rows = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        low = ln.lower()
        if low.startswith("id") or low.startswith("nombre"):
            continue

        # Caso TSV (lo más común al copiar desde Excel)
        if "\t" in ln:
            parts = [p.strip() for p in ln.split("\t") if p.strip() != ""]
            if len(parts) >= 4:
                id_fuente = int(parts[0])
                slug = parts[1]
                nombre = _clean_nombre(parts[2])
                tipo = parts[3]
                rows.append((id_fuente, slug, nombre, tipo))
                continue

        # Caso por espacios (si te lo pega sin tabs)
        m = re.match(
            r"^(\d+)\s+([A-Za-z0-9_]+)\s+(.*?)\s+(Internacional|Nacional|Colegio Regulador)\s*$",
            ln,
        )
        if not m:
            raise ValueError(f"No pude interpretar esta línea: {ln!r}")

        id_fuente = int(m.group(1))
        slug = m.group(2)
        nombre = _clean_nombre(m.group(3))
        tipo = m.group(4)
        rows.append((id_fuente, slug, nombre, tipo))

    return rows


def main():
    # Asegura que encuentre el proyecto si ejecutas desde la carpeta de manage.py
    PROJECT_ROOT = Path(__file__).resolve().parent
    sys.path.insert(0, str(PROJECT_ROOT))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    django.setup()

    from core.models import Fuente, TipoFuente  # noqa

    rows = parse_rows(RAW)
    pk_name = Fuente._meta.pk.name  # por si tu PK no se llama "id"

    tipo_cache = {}


    with transaction.atomic():
        for id_fuente, slug, nombre, tipo_nombre in rows:
            tipo_obj = tipo_cache.get(tipo_nombre)
            if tipo_obj is None:
                tipo_obj, _ = TipoFuente.objects.get_or_create(nombre=tipo_nombre)
                tipo_cache[tipo_nombre] = tipo_obj

            # CORREGIDO: nombre=slug, nombre_pila=nombre
            defaults = {"nombre": slug, "nombre_pila": nombre, "tipo": tipo_obj}
            lookup = {pk_name: id_fuente}

            try:
                # Actualiza/crea por ID (PK)
                Fuente.objects.update_or_create(**lookup, defaults=defaults)
            except IntegrityError:
                # Si choca por unique nombre, actualiza por nombre (no cambia el ID existente)
                obj = Fuente.objects.get(nombre=slug)
                obj.nombre_pila = nombre
                obj.tipo = tipo_obj
                obj.save(update_fields=["nombre_pila", "tipo"])

    print(f"Fuentes registradas correctamente. Procesadas: {len(rows)}")


if __name__ == "__main__":
    main()
