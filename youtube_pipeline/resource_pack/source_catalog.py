from __future__ import annotations


APPROVED_SOURCE_CATALOG = [
    {
        "title": "岸見一郎公式ホームページ",
        "url": "https://kishimi.com/",
        "supports": "岸見一郎の公式プロフィール、著作・講演情報",
    },
    {
        "title": "嫌われる勇気｜ダイヤモンド社",
        "url": "https://www.diamond.co.jp/book/9784478025819.html",
        "supports": "岸見一郎・古賀史健の共著情報と課題の分離を含む目次",
        "publication_year": 2013,
        "authors": ["岸見一郎", "古賀史健"],
        "publisher": "ダイヤモンド社",
        "citation_hint": "岸見一郎・古賀史健（2013）『嫌われる勇気』ダイヤモンド社",
    },
    {
        "title": "岸見一郎｜Wikipedia日本語版",
        "url": "https://ja.wikipedia.org/wiki/岸見一郎",
        "supports": "経歴の補助確認。主張の一次根拠には使わない",
    },
    {
        "title": "嫌われる勇気｜Wikipedia日本語版",
        "url": "https://ja.wikipedia.org/wiki/嫌われる勇気",
        "supports": "書籍の基本情報の補助確認。主張の一次根拠には使わない",
        "publication_year": 2013,
        "citation_hint": "『嫌われる勇気』（2013年）",
    },
    {
        "title": "Learned helplessness at fifty: Insights from neuroscience",
        "url": "https://doi.org/10.1037/rev0000033",
        "supports": (
            "Maier and Seligman review how uncontrollable stress can suppress later escape behavior "
            "and distinguish learned control from a deterministic helplessness explanation."
        ),
        "authors": ["Steven F. Maier", "Martin E. P. Seligman"],
        "publication_year": 2016,
        "publisher": "American Psychological Association",
        "citation_hint": "Maier & Seligman (2016), Psychological Review, 123(4), 349-367",
        "allowed_paraphrases": [
            "経験したコントロールの有無は、その後の反応に影響する可能性があります",
            "無力さを性格の欠陥として決めつけず、状況と学習の影響を分けて考えます",
        ],
        "forbidden_attributions": [
            "逆境が必ず人を強くするという断定",
            "すべての抑うつや停止反応をこの研究だけで説明すること",
        ],
    },
    {
        "title": "Everyday temptations: An experience sampling study of desire, conflict, and self-control",
        "url": "https://doi.org/10.1037/a0026545",
        "supports": (
            "Experience-sampling research reported that people with higher self-control experienced "
            "less desire and conflict in daily life, rather than simply resisting more urges."
        ),
        "authors": ["Wilhelm Hofmann", "Roy F. Baumeister", "Georg Förster", "Kathleen D. Vohs"],
        "publication_year": 2012,
        "publisher": "American Psychological Association",
        "citation_hint": "Hofmann et al. (2012), Journal of Personality and Social Psychology, 102(6), 1318-1335",
        "allowed_paraphrases": [
            "自己コントロールが高い人は、日常で欲求との葛藤を経験する頻度が低い傾向を示しました",
            "意志力で毎回勝つことだけが自己コントロールではありません",
        ],
        "forbidden_attributions": [
            "自己コントロールが高い人は欲求を一切持たないという断定",
            "この相関だけで特定の習慣を作れると保証すること",
        ],
    },
    {
        "title": "Hidden talents in harsh environments",
        "url": "https://doi.org/10.1017/s0954579420000887",
        "supports": (
            "Ellis and colleagues describe a hidden-talents model in which some stress-adapted skills "
            "may help people function in harsh, unpredictable environments; the model is not a claim "
            "that adversity is beneficial or that every person develops the same skill."
        ),
        "authors": [
            "Bruce J. Ellis", "Laura S. Abrams", "Ann S. Masten", "Robert J. Sternberg",
            "Nim Tottenham", "Willem E. Frankenhuis",
        ],
        "publication_year": 2022,
        "publisher": "Cambridge University Press",
        "citation_hint": "Ellis et al. (2022), Development and Psychopathology, 34(1), 95-113",
        "allowed_paraphrases": [
            "厳しい環境に適応する中で、特定の状況に役立つ技能が発達する可能性があります",
            "これは逆境を美化する話ではなく、適応の機能と代償を同時に見る視点です",
        ],
        "forbidden_attributions": [
            "逆境やトラウマが知能を高めるという断定",
            "厳しい環境で育った人は全員同じ能力を持つという一般化",
            "特定の視聴者に childhood trauma や診断を割り当てること",
        ],
    },
    {
        "title": "Annual Research Review: Positive adjustment to adversity - trajectories of minimal-impact resilience and emergent resilience",
        "url": "https://doi.org/10.1111/jcpp.12021",
        "supports": (
            "Bonanno and colleagues review resilience trajectories and emphasize that positive adjustment "
            "can follow different paths; resilience should not be reduced to emotional toughness or one fixed trait."
        ),
        "authors": ["George A. Bonanno", "Anthony D. Mancini"],
        "publication_year": 2012,
        "publisher": "Wiley",
        "citation_hint": "Bonanno & Mancini (2012), Journal of Child Psychology and Psychiatry, 54(4), 378-401",
        "allowed_paraphrases": [
            "回復には複数の軌跡があり、柔軟な適応として捉える必要があります",
            "強さを感情が揺れないことと同一視しません",
        ],
        "forbidden_attributions": [
            "誰でも同じ期間で回復するという断定",
            "回復できない人は努力不足だという評価",
        ],
    },
    {
        "title": "Risk, resilience, and recovery: Perspectives from the Kauai Longitudinal Study",
        "url": "https://doi.org/10.1017/s095457940000612x",
        "supports": (
            "Werner's longitudinal work describes resilience and recovery in the Kauai study and the role "
            "of supportive relationships and meaningful responsibilities; it does not establish a single cause."
        ),
        "authors": ["Emmy E. Werner"],
        "publication_year": 1993,
        "publisher": "Cambridge University Press",
        "citation_hint": "Werner (1993), Development and Psychopathology, 5(4), 503-515",
        "allowed_paraphrases": [
            "支えてくれる大人や意味のある役割は、適応を支える要素になり得ます",
            "長期的な適応には複数の保護要因が関わります",
        ],
        "forbidden_attributions": [
            "一人の支援者がいれば必ず回復するという約束",
            "過去の adversity だけから現在の人格を決めつけること",
        ],
    },
    {
        "title": "A Neural Substrate of Prediction and Reward",
        "url": "https://doi.org/10.1126/science.275.5306.1593",
        "supports": (
            "Schultz and colleagues reported dopamine-neuron responses related to reward prediction and "
            "prediction error in primates; this is not a complete theory of human motivation."
        ),
        "authors": ["Wolfram Schultz", "Peter Dayan", "P. Read Montague"],
        "publication_year": 1997,
        "publisher": "AAAS",
        "citation_hint": "Schultz, Dayan, & Montague (1997), Science, 275(5306), 1593-1599",
        "allowed_paraphrases": [
            "報酬の予測と予測誤差に関わる神経信号が研究されています",
            "脳は報酬そのものだけでなく、予測とのずれにも反応します",
        ],
        "forbidden_attributions": [
            "ドーパミンを快楽物質とだけ説明すること",
            "この研究だけで個人のやる気や習慣を断定すること",
        ],
    },
    {
        "title": "Psychology of Habit",
        "url": "https://doi.org/10.1146/annurev-psych-122414-033417",
        "supports": (
            "Wood and Runger review habits as learned responses shaped by repetition and context, "
            "with behavior becoming less dependent on deliberative intention in stable contexts."
        ),
        "authors": ["Wendy Wood", "Dennis Runger"],
        "publication_year": 2016,
        "publisher": "Annual Reviews",
        "citation_hint": "Wood & Runger (2016), Annual Review of Psychology, 67, 289-314",
        "allowed_paraphrases": [
            "習慣は意志の強さだけでなく、反復と状況の手がかりによって形成されます",
            "環境を変えることは、行動のきっかけを変える方法の一つです",
        ],
        "forbidden_attributions": [
            "習慣が必ず一定日数で自動化するという断定",
            "環境設計だけですべての心理的問題が解決するという主張",
        ],
    },
    {
        "title": "Holding the Hunger Games Hostage at the Gym: An Evaluation of Temptation Bundling",
        "url": "https://doi.org/10.1287/mnsc.2013.1784",
        "supports": (
            "Milkman and colleagues evaluated pairing an immediately enjoyable activity with a should-do "
            "activity as a behavioral intervention; the effect depends on context and adherence."
        ),
        "authors": ["Katherine L. Milkman", "Julia A. Minson", "Kevin G. Volpp"],
        "publication_year": 2014,
        "publisher": "INFORMS",
        "citation_hint": "Milkman, Minson, & Volpp (2014), Management Science, 60(5), 1231-1235",
        "allowed_paraphrases": [
            "楽しみな行動と取り組むべき行動を組み合わせる設計が検討されています",
            "報酬の置き方を変えることで、行動の始めやすさを調整できます",
        ],
        "forbidden_attributions": [
            "この方法がすべての人に同じ効果を持つという保証",
            "研究結果を『脳をだます』という断定的な神経科学説明に変えること",
        ],
    },
    {
        "title": "The Effort Paradox: Effort Is Both Costly and Valued",
        "url": "https://doi.org/10.1016/j.tics.2018.01.007",
        "supports": (
            "Inzlicht and colleagues review evidence that effort can be experienced as costly while also "
            "being valued in some contexts; effort is not uniformly aversive or rewarding."
        ),
        "authors": ["Michael Inzlicht", "Aria Z. Shenhav", "Christopher Y. Olivola"],
        "publication_year": 2018,
        "publisher": "Elsevier",
        "citation_hint": "Inzlicht, Shenhav, & Olivola (2018), Trends in Cognitive Sciences, 22(4), 337-349",
        "allowed_paraphrases": [
            "努力は負担であると同時に、状況によって価値を持つことがあります",
            "難しさを感じることだけで、その行動が無価値だとは言えません",
        ],
        "forbidden_attributions": [
            "努力すれば必ず楽しくなるという断定",
            "努力を選ばない人を怠け者と決めつけること",
        ],
    },
    {
        "title": "Ordinary magic: Resilience processes in development",
        "url": "https://doi.org/10.1037/0003-066X.56.3.227",
        "supports": (
            "Masten frames resilience as ordinary adaptive processes rather than a rare superpower, "
            "while emphasizing that outcomes depend on developmental and environmental conditions."
        ),
        "authors": ["Ann S. Masten"],
        "publication_year": 2001,
        "publisher": "American Psychological Association",
        "citation_hint": "Masten (2001), American Psychologist, 56(3), 227-238",
        "allowed_paraphrases": [
            "回復力は特別な才能ではなく、複数の普通の適応過程から生まれることがあります",
            "環境と発達の条件を無視して、個人の強さだけに還元しません",
        ],
        "forbidden_attributions": [
            "すべての人が同じ支援なしで回復できるという断定",
            "レジリエンスを精神論や根性論だけで説明すること",
        ],
    },
    {
        "title": "The Collected Works of C. G. Jung, Vol. 9 Part 1: The Archetypes and the Collective Unconscious",
        "url": "https://doi.org/10.1515/9781400850969",
        "supports": (
            "Jung describes individuation (個性化), archetypes, and the collective unconscious as an "
            "interpretive framework for psychological development, not as empirically proven mechanisms."
        ),
        "authors": ["C. G. Jung"],
        "publication_year": 1969,
        "publisher": "Princeton University Press",
        "citation_hint": "Jung, C. G. (1969), Collected Works Vol. 9.1, Princeton University Press",
        "allowed_paraphrases": [
            "個性化とは、無意識の側面を意識に統合していく過程として語られます",
            "元型や集合的無意識は、体験を解釈するための枠組みとして用います（証明された因果ではありません）",
        ],
        "forbidden_attributions": [
            "ユング理論を科学的に証明された事実として断定すること",
            "視聴者個人の幼少期トラウマや診断をこの枠組みだけで決めつけること",
        ],
    },
    {
        "title": "The Collected Works of C. G. Jung, Vol. 9 Part 2: Aion — Researches into the Phenomenology of the Self",
        "url": "https://doi.org/10.1515/9781400851058",
        "supports": (
            "Jung develops the shadow (シャドウ) and the Self as symbolic structures of the psyche, "
            "framed as an interpretive lens for self-integration rather than a clinical diagnosis."
        ),
        "authors": ["C. G. Jung"],
        "publication_year": 1969,
        "publisher": "Princeton University Press",
        "citation_hint": "Jung, C. G. (1969), Aion, Collected Works Vol. 9.2, Princeton University Press",
        "allowed_paraphrases": [
            "シャドウとは、自分が認めにくい側面を象徴的に指す言葉として用います",
            "自己統合は、否認していた部分を意識に含めていく象徴的な過程として語られます",
        ],
        "forbidden_attributions": [
            "シャドウ統合が特定の症状を必ず治すという断定",
            "象徴的な解釈を医学的診断として提示すること",
        ],
    },
]

# Backward-compatible name used by existing imports and generated artifacts.
KISHIMI_SOURCE_CATALOG = APPROVED_SOURCE_CATALOG
KNOWN_SOURCE_URLS = {row["url"] for row in APPROVED_SOURCE_CATALOG}
