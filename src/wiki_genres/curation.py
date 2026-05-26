"""Manual curation rules shared by crawls, filters, and migrations.

The automatic classifier intentionally stays strict. Titles in
``MANUAL_MUSIC_GENRE_TITLES`` are pages the project has reviewed and wants to
keep even when Wikipedia does not expose the usual infobox or Wikidata genre
signals.
"""

from __future__ import annotations

from dataclasses import dataclass

MUSIC_GENRE_CLASS_QIDS = {
    "Q188451",  # music genre
    "Q2944929",  # musical style
}

MUSIC_CATEGORY_MARKERS = (
    "music genre",
    "music genres",
    "musical genre",
    "musical genres",
    "music style",
    "music styles",
    "musical style",
    "musical styles",
    "styles of music",
)

MANUAL_CURATION_EDGE_SOURCE = "manual_curation"

MANUAL_HIGH_LEVEL_ROOT_TITLES = ("Religious music", "Latin music")

MANUAL_NON_GENRE_TITLES = {
    "Popular music",
}


@dataclass(frozen=True)
class ManualDisplayEdge:
    parent_title: str
    child_title: str
    relation: str = "subgenre"


MANUAL_DISPLAY_EDGES = (
    ManualDisplayEdge("Soundtrack", "Film score"),
    ManualDisplayEdge("Soundtrack", "Theme music"),
    ManualDisplayEdge("Soundtrack", "Theatre music"),
    ManualDisplayEdge("Folk music", "Work song"),
    ManualDisplayEdge("Electronic dance music", "Bass music"),
    ManualDisplayEdge("Hip-hop", "Bass music"),
    ManualDisplayEdge("Rock music", "Psychedelic music"),
    ManualDisplayEdge("Rock music", "Visual kei"),
    ManualDisplayEdge("Heavy metal music", "Visual kei"),
    ManualDisplayEdge("Christian music", "Contemporary Christian music"),
    ManualDisplayEdge("Religious music", "Contemporary Christian music"),
    ManualDisplayEdge("Folk music", "Contemporary folk music"),
    ManualDisplayEdge("Pop music", "Children's music"),
    ManualDisplayEdge("Folk music", "Dangdut"),
    ManualDisplayEdge("Hip-hop", "Hipdut"),
    ManualDisplayEdge("Dangdut", "Hipdut"),
    ManualDisplayEdge("Religious music", "Modern pagan music"),
    ManualDisplayEdge("Folk music", "Modern pagan music"),
    ManualDisplayEdge("Comedy music", "Nerd music"),
    ManualDisplayEdge("Novelty song", "Nerd music"),
    ManualDisplayEdge("Pop music", "Nerd music"),
    ManualDisplayEdge("Vocal music", "Parlour music"),
    ManualDisplayEdge("Pop music", "Parlour music"),
    ManualDisplayEdge("Chanson", "Russian chanson"),
    ManualDisplayEdge("Folk music", "Russian chanson"),
    ManualDisplayEdge("Electronic music", "Sampledelia"),
    ManualDisplayEdge("Hip-hop", "Sampledelia"),
    ManualDisplayEdge("Psychedelic music", "Sampledelia"),
    ManualDisplayEdge("Vocal music", "Sentimental ballad"),
    ManualDisplayEdge("Pop music", "Italian popular music"),
    ManualDisplayEdge("Pop music", "Malaysian popular music"),
    ManualDisplayEdge("Pop music", "Pakistani popular music"),
    ManualDisplayEdge("Pop music", "Popular music of Vietnam"),
    ManualDisplayEdge("Pop music", "Contemporary commercial music"),
    ManualDisplayEdge("Jazz", "Contemporary commercial music"),
    ManualDisplayEdge("Blues", "Contemporary commercial music"),
    ManualDisplayEdge("Soul music", "Contemporary commercial music"),
    ManualDisplayEdge("Country music", "Contemporary commercial music"),
    ManualDisplayEdge("Folk music", "Contemporary commercial music"),
    ManualDisplayEdge("Rock music", "Contemporary commercial music"),
    ManualDisplayEdge("Christmas music", "Holiday music"),
    ManualDisplayEdge("Religious music", "Holiday music"),
    ManualDisplayEdge("Music of Indonesia", "Gamelan"),
    ManualDisplayEdge("Music of South Korea", "Traditional music of Korea"),
    ManualDisplayEdge("Music of North Korea", "Traditional music of Korea"),
    ManualDisplayEdge("Music of the Democratic Republic of the Congo", "Congolese rumba"),
    ManualDisplayEdge("Music of the Republic of the Congo", "Congolese rumba"),
    ManualDisplayEdge("Music of Tanzania", "Congolese rumba"),
    ManualDisplayEdge("Music of the United States", "Indigenous music of North America"),
    ManualDisplayEdge("Music of Canada", "Indigenous music of North America"),
    ManualDisplayEdge("Music of Mexico", "Indigenous music of North America"),
    ManualDisplayEdge("Music of Ireland", "Celtic music"),
    ManualDisplayEdge("Music of Scotland", "Celtic music"),
    ManualDisplayEdge("Music of Brittany", "Celtic music"),
    ManualDisplayEdge("Music of Finland", "Nordic folk music"),
    ManualDisplayEdge("Music of Argentina", "Tango"),
    ManualDisplayEdge("Music of Uruguay", "Tango"),
    ManualDisplayEdge("Music of Portugal", "Fado"),
    ManualDisplayEdge("Music of India", "Ghazal"),
    ManualDisplayEdge("Music of Pakistan", "Ghazal"),
)

MANUAL_REVIEWED_STYLE_TITLES = {
    "Ahwash n tferkhin",
    "Alap",
    "Alternative Joropo",
    "Arabic maqam",
    "Arrochadeira",
    "Ayacuchan Carnival",
    "Bajidor",
    "Ballad",
    "Battlemix",
    "Batuque (Brazil)",
    "Biguine ka",
    "Biguine vidé",
    "Boliyan",
    "Booty bass",
    "Breakbeat Kota",
    "British folk revival",
    "Burru",
    "Caipira samba",
    "Chalupa (music)",
    "Chanson éxotique",
    "Charanga (Cuba)",
    "Chicha music",
    "Chilean cumbia",
    "Chinese yellow music",
    "Chunchaca",
    "Coastal taarab",
    "Colour house",
    "Creole Joropo",
    "Dangdut House",
    "Dangdut bumbung",
    "Dangdut dendang saluang",
    "Dangdut electro",
    "Dangdut gondang",
    "Dangdut jaipong",
    "Dangdut kalimantan",
    "Dangdut pantura",
    "Dangdut rampak",
    "Dangdut tarling",
    "Devotional song",
    "Edo Highlife",
    "Electro trance",
    "Embolada",
    "Estrada",
    "Euro deep house (genre)",
    "Flint rap",
    "Full bass",
    "Grand chant",
    "Hiyawa",
    "Honky-tonk",
    "Ijaw Highlife",
    "Impressionism in music",
    "Jhala",
    "Juju",
    "Leammt",
    "Malagueñas (flamenco style)",
    "Milonga candombe",
    "Muzak",
    "Neoclassicism (music)",
    "Nyabinghi rhythm",
    "Operetta",
    "Peak time techno",
    "Psy-tech trance",
    "Rare groove",
    "Rhythmic adult contemporary",
    "Romantic Joropo",
    "Samba duro",
    "Scat singing",
    "Soleá",
    "Soundtrack",
    "Spoken word",
    "Straight edge",
    "String band",
    "Tagonggo",
    "Tala (music)",
    "Tango",
    "Tango (flamenco)",
    "Tientos (flamenco)",
    "Toasting (Jamaican music)",
    "Tuk band",
    "Turkish makam",
    "Urban adult contemporary",
    "Valse musette",
    "Vaneira",
    "Verdiales",
    "Vocal jazz",
    "Waltz",
    "Zambapalo",
    "Zarzuela",
}

MANUAL_MUSIC_OF_COUNTRY_TITLES = {
    "Music of Antigua and Barbuda",
    "Music of Barbados",
    "Music of Dominica",
    "Music of Eswatini",
    "Music of Grenada",
    "Music of Kiribati",
    "Music of Kuwait",
    "Music of Montenegro",
    "Music of Northern Cyprus",
    "Music of South Sudan",
    "Music of Trinidad and Tobago",
    "Music of Wales",
    "Music of Western Sahara",
    "Music of the Bahamas",
    "Music of the Cook Islands",
    "Music of the Federated States of Micronesia",
    "Music of the Marshall Islands",
    "Music of the United Arab Emirates",
    "Music of Tokelau",
    "Music of Tuvalu",
    "Music of Vanuatu",
}

MANUAL_MUSIC_GENRE_TITLES = MANUAL_REVIEWED_STYLE_TITLES | MANUAL_MUSIC_OF_COUNTRY_TITLES
