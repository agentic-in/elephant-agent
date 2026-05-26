% %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Lightweight paper class for the Elephant Agent system report
% Revised to match vLLM-style tcolorbox title layout.
% %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{elephant}
\LoadClassWithOptions{article}
\makeatletter

\renewcommand{\topfraction}{0.95}
\renewcommand{\bottomfraction}{0.85}
\renewcommand{\textfraction}{0.05}
\renewcommand{\floatpagefraction}{0.8}
\setcounter{topnumber}{4}
\setcounter{bottomnumber}{2}
\setcounter{totalnumber}{6}

\RequirePackage[expansion=false]{microtype}
\IfFileExists{placeins.sty}{\RequirePackage{placeins}}{\providecommand{\FloatBarrier}{}}
\IfFileExists{hyphenat.sty}{\RequirePackage{hyphenat}}{}
\RequirePackage{setspace}
\RequirePackage{parskip}
\RequirePackage[english]{babel}
\RequirePackage{etoolbox}
\RequirePackage{fancyhdr}
\IfFileExists{float.sty}{\RequirePackage{float}}{}

\DisableLigatures[f]{family=sf*}

\RequirePackage{graphicx}
\RequirePackage{subcaption}
\RequirePackage{booktabs}
\RequirePackage{multirow}
\RequirePackage{bm}
\newcommand{\nm}[1]{#1}

% ── Colour palette ────────────────────────────────────────────────────────────
\RequirePackage{xcolor}
\definecolor{elephantnavy}{HTML}{24384D}
\definecolor{elephantblue}{HTML}{3E5C76}
\definecolor{elephantslate}{HTML}{7089A3}
\definecolor{elephantsky}{HTML}{A8C0D5}
\definecolor{elephantice}{HTML}{DCE7F1}
\definecolor{elephantfoam}{HTML}{EEF4F8}
\definecolor{elephantfg}{HTML}{1F2937}
\definecolor{elephantbg}{HTML}{F7FAFC}   % title-box background
\definecolor{elephantline}{HTML}{C7D4DF}
\definecolor{elephantfill}{HTML}{E7EEF5}
\definecolor{elephantrule}{HTML}{4D4D4D}

% ── Hyperlinks ────────────────────────────────────────────────────────────────
\RequirePackage{hyperref}
\hypersetup{
  colorlinks,
  linkcolor=elephantblue,
  citecolor=elephantblue,
  urlcolor=elephantblue
}

% ── Section / caption format ──────────────────────────────────────────────────
\IfFileExists{titlesec.sty}{
  \RequirePackage{titlesec}
  \titleformat*{\paragraph}{\itshape}
  \titleformat*{\section}{\Large\sffamily\bfseries}
  \titleformat*{\subsection}{\large\sffamily\bfseries}
  \titleformat*{\subsubsection}{\normalsize\sffamily\bfseries}
}{}
\DeclareTextFontCommand{\textbf}{\bfseries\sffamily}

\RequirePackage{caption}
\DeclareCaptionLabelSeparator{elephantcustom}{}
\DeclareCaptionFormat{elephantcustom}{{\sffamily\textbf{#1 #2}} #3}
\captionsetup{singlelinecheck=false,format=elephantcustom,labelsep=elephantcustom,font=small}
\captionsetup[sub]{singlelinecheck=true,format=elephantcustom,labelsep=elephantcustom,font=small}

% ── Fonts ─────────────────────────────────────────────────────────────────────
\RequirePackage[T1]{fontenc}
\IfFileExists{tgpagella.sty}{\RequirePackage{tgpagella}}{\IfFileExists{lmodern.sty}{\RequirePackage{lmodern}}{}}
\IfFileExists{inconsolata.sty}{\RequirePackage{inconsolata}}{}
\renewcommand{\sfdefault}{cmss}

% ── Author / affiliation / metadata helpers ───────────────────────────────────
\newcommand\authorlist{}
\providecommand{\@author}{}
\renewcommand{\author}[1]{%
  \gdef\@author{#1}%
  \def\authorlist{\par{\large\sffamily\bfseries\@author}}%
}

\newcommand{\affiliationlist}{}
\newcommand{\affiliation}[2][]{%
  \ifdefempty{\affiliationlist}
    {\gdef\affiliationlist{$^{#1}$#2}}
    {\g@addto@macro\affiliationlist{, $^{#1}$#2}}%
}

\newcommand{\metadatalist}{}
\protected\def\metadataformat#1#2{{\small {\sffamily\bfseries #1:} #2}}
\newcommand\metadata[2][]{%
  \ifdefempty{\metadatalist}
    {\gdef\metadatalist{\metadataformat{#1}{#2}}}
    {\g@addto@macro\metadatalist{\par\metadataformat{#1}{#2}}}%
}

\newcommand{\abstractlist}{}
\long\def\abstract#1{\def\abstractlist{{\color{elephantfg} #1}}}
\newcommand{\email}[1]{\href{mailto:#1}{\texttt{#1}}}

\providecommand{\@date}{}
\renewcommand\date[1]{%
  \gdef\@date{#1}%
  \def\metadatalist{\metadataformat{Date}{#1}}%
}
\newcommand\correspondence[1]{\metadata[Correspondence]{#1}}

\providecommand{\@title}{}
\newcommand{\@subtitle}{}
\renewcommand{\title}[1]{%
  \gdef\@title{#1}%
  \def\titlelist{{\huge\sffamily\bfseries #1}}%
}
\newcommand{\subtitle}[1]{%
  \gdef\@subtitle{#1}%
  \def\subtitlelist{{\Large #1}}%
}
\newcommand{\subtitlelist}{}

% ── Logo / brand dimensions (mirror vllm knobs) ───────────────────────────────
\newcommand{\elephantTitleMetaColumnWidth}{0.52\textwidth}
\newcommand{\elephantTitleLogoColumnWidth}{0.3\textwidth}
\newcommand{\elephantProductLogoGraphicWidth}{2.75cm}
\newcommand{\elephantTitleLogoGraphicWidth}{2.5cm}
\newcommand{\elephantTitleLogoHSpace}{\hspace{0pt}}
\newcommand{\elephantTitleLogoRaise}{\raisebox{0pt}}

% ── Running header ────────────────────────────────────────────────────────────
\newcommand{\elephantHeaderWidth}{\textwidth}
\newcommand{\elephantRunningTitle}{Elephant Agent: Agency-First Personal AI}
\newcommand{\elephantRunningHeaderBar}{%
  {\small\color{elephantfg}\elephantRunningTitle\hfill\color{elephantfg}\thepage}\par
  \vspace{-0.52em}%
  {\color{elephantrule}\rule{\linewidth}{0.9pt}}%
}
\newcommand{\elephantFirstPageBrandBar}{%
  {\includegraphics[height=10mm]{assets/logo_AIL.png}%
   \hfill\normalsize\color{elephantfg}\@date}\par
  \vspace{-0.52em}%
  {\color{elephantrule}\rule{\linewidth}{0.9pt}}%
}
\newcommand{\elephantHeaderBox}[1]{%
  \begin{minipage}[b]{\textwidth}#1\end{minipage}%
}

\pagestyle{fancy}
\fancyhf{}
\AtBeginDocument{\setlength{\headwidth}{\textwidth}}
\fancyhead[L]{\small\color{elephantfg}\elephantRunningTitle}
\fancyhead[R]{\small\color{elephantfg}\thepage}
\fancyfoot{}
\renewcommand{\headrulewidth}{0.9pt}
\renewcommand{\footrulewidth}{0pt}

\fancypagestyle{firstpage}{%
  \fancyhf{}
  \fancyhead[L]{\includegraphics[height=10mm]{assets/logo_AIL.png}}
  \fancyhead[R]{\normalsize\color{elephantfg}\@date}
  \fancyfoot[C]{\thepage}
  \renewcommand{\headrulewidth}{0.9pt}
  \renewcommand{\footrulewidth}{0pt}
}

\newcommand{\beginappendix}{\appendix{\huge\sffamily Appendix\par}}

% ── Title box ────────────────────────────────────────────────────────────────
\newcommand{\mymaketitle}{%
  \begingroup
  \setlength{\fboxsep}{0.5cm}%
  \noindent\colorbox{elephantbg}{%
  \begin{minipage}{\dimexpr\textwidth-2\fboxsep\relax}
    \setlength{\parindent}{0cm}
    \setlength{\parskip}{0.1cm}

    \begin{center}
      {\includegraphics[width=\elephantProductLogoGraphicWidth]{assets/elephant-logo.png}\par}
      \vspace{0.65em}
      {\LARGE\bfseries \@title\par}
      \ifdefempty{\@subtitle}{}{\vspace{0.5em}{\large\bfseries \@subtitle\par}}
      \vspace{1.0em}
      {\normalsize \@author\par}
      \ifdefempty{\affiliationlist}{}{%
        \vspace{0.5em}%
        {\small \affiliationlist\par}%
      }%
    \end{center}

    \vspace{1.0em}

    \ifdefempty{\abstractlist}{}{%
      \noindent{\sffamily\bfseries Abstract. }\abstractlist\par
    }

    \noindent
    \begin{minipage}[t]{0.56\linewidth}
      \raggedright
      \ifdefempty{\metadatalist}{}{{\small \metadatalist}}
    \end{minipage}%
    \hfill
    \begin{minipage}[t]{0.32\linewidth}
      \raggedleft
      \elephantTitleLogoHSpace\elephantTitleLogoRaise{%
        \includegraphics[width=\elephantTitleLogoGraphicWidth]{assets/logo_AIL.png}%
      }%
    \end{minipage}

  \end{minipage}%
  }%
  \par
  \endgroup
  \thispagestyle{firstpage}
  \FloatBarrier
}

\if@twocolumn%
\renewcommand{\maketitle}{%
\twocolumn[%
  \mymaketitle
  \vskip 0.3cm
]%
}%
\else%
\renewenvironment{figure*}{\@float{figure}}{\end@float}
\renewenvironment{table*}{\@float{table}}{\end@float}
\renewcommand{\maketitle}{%
  \mymaketitle
}%
\fi
\makeatother
