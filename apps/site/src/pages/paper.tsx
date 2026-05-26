import React, { useCallback, useEffect, useRef, useState } from 'react'
import Layout from '@theme/Layout'
import Head from '@docusaurus/Head'
import BrowserOnly from '@docusaurus/BrowserOnly'
import useDocusaurusContext from '@docusaurus/useDocusaurusContext'
import styles from './paper.module.css'

const PDF_URL = '/assets/paper.pdf'
const MOBILE_BREAKPOINT = 768
const MAX_SPREAD_VIEWPORT_WIDTH = 1400
const VIEWPORT_SIDE_PADDING = 120
const SPREAD_GAP = 16
const PDF_PAGE_RATIO = Math.SQRT2
const VIEWER_TOOLBAR_HEIGHT = 56
const PAGINATION_HEIGHT = 56
const VIEWER_VERTICAL_PADDING = 48
const MIN_SPREAD_PAGE_WIDTH = 620
const SPREAD_FILL_THRESHOLD = 0.82
const MAX_SINGLE_PAGE_WIDTH = 980

type FullscreenCapableDocument = Document & {
  webkitExitFullscreen?: () => Promise<void> | void
  webkitFullscreenElement?: Element | null
}

type FullscreenCapableElement = HTMLElement & {
  webkitRequestFullscreen?: () => Promise<void> | void
}

function getFullscreenElement(): Element | null {
  const fullscreenDocument = document as FullscreenCapableDocument
  return document.fullscreenElement ?? fullscreenDocument.webkitFullscreenElement ?? null
}

function PaperViewerContent(): React.JSX.Element {
  const { Document, Page, pdfjs } = require('react-pdf') as typeof import('react-pdf')
  require('react-pdf/dist/Page/AnnotationLayer.css')
  require('react-pdf/dist/Page/TextLayer.css')

  pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

  const viewerShellRef = useRef<HTMLDivElement | null>(null)
  const [numPages, setNumPages] = useState<number>(0)
  const [pageNumber, setPageNumber] = useState<number>(1)
  const [pageWidth, setPageWidth] = useState<number>(600)
  const [isMobile, setIsMobile] = useState<boolean>(false)
  const [isSpread, setIsSpread] = useState<boolean>(true)
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false)
  const [canToggleFullscreen, setCanToggleFullscreen] = useState<boolean>(false)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<boolean>(false)

  const updateSize = useCallback(() => {
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight
    const mobile = viewportWidth <= MOBILE_BREAKPOINT

    setIsMobile(mobile)

    if (mobile) {
      setIsSpread(false)
      setPageWidth(Math.max(320, viewportWidth - 2))
      return
    }

    const availableWidth = Math.min(
      viewportWidth - VIEWPORT_SIDE_PADDING,
      MAX_SPREAD_VIEWPORT_WIDTH,
    )
    const spreadPageWidth = Math.floor(availableWidth / 2) - SPREAD_GAP
    const viewerHeight = Math.max(
      viewportHeight - VIEWER_TOOLBAR_HEIGHT - PAGINATION_HEIGHT - VIEWER_VERTICAL_PADDING,
      1,
    )
    const spreadPageHeight = spreadPageWidth * PDF_PAGE_RATIO
    const spreadFillsViewport = spreadPageHeight >= viewerHeight * SPREAD_FILL_THRESHOLD
    const canUseSpread =
      spreadPageWidth >= MIN_SPREAD_PAGE_WIDTH && spreadFillsViewport

    setIsSpread(canUseSpread)

    if (canUseSpread) {
      setPageWidth(spreadPageWidth)
      return
    }

    const widthByViewport = Math.min(viewportWidth - 96, MAX_SINGLE_PAGE_WIDTH)
    const widthByHeight = Math.floor(viewerHeight / PDF_PAGE_RATIO)

    setPageWidth(Math.max(320, Math.min(widthByViewport, widthByHeight)))
  }, [])

  useEffect(() => {
    const fullscreenDocument = document as FullscreenCapableDocument
    const viewerShell = viewerShellRef.current as FullscreenCapableElement | null

    setCanToggleFullscreen(Boolean(
      document.fullscreenEnabled
      || fullscreenDocument.webkitExitFullscreen
      || viewerShell?.requestFullscreen
      || viewerShell?.webkitRequestFullscreen
    ))
  }, [])

  useEffect(() => {
    const handleViewportChange = () => updateSize()

    updateSize()
    window.addEventListener('resize', handleViewportChange)
    document.addEventListener('fullscreenchange', handleViewportChange)
    document.addEventListener('webkitfullscreenchange', handleViewportChange)

    return () => {
      window.removeEventListener('resize', handleViewportChange)
      document.removeEventListener('fullscreenchange', handleViewportChange)
      document.removeEventListener('webkitfullscreenchange', handleViewportChange)
    }
  }, [updateSize])

  useEffect(() => {
    const handleFullscreenChange = () => {
      const fullscreenElement = getFullscreenElement()
      const viewerShell = viewerShellRef.current
      const isViewerFullscreen = Boolean(
        fullscreenElement
        && viewerShell
        && (fullscreenElement === viewerShell || viewerShell.contains(fullscreenElement))
      )

      setIsFullscreen(isViewerFullscreen)
    }

    handleFullscreenChange()
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    document.addEventListener('webkitfullscreenchange', handleFullscreenChange)

    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange)
      document.removeEventListener('webkitfullscreenchange', handleFullscreenChange)
    }
  }, [])

  useEffect(() => {
    setPageNumber((current) => {
      const maxPage = numPages > 0 ? numPages : 1
      let next = Math.min(Math.max(current, 1), maxPage)

      if (isSpread && next % 2 === 0)
        next = Math.max(1, next - 1)

      return next
    })
  }, [isSpread, numPages])

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages)
    setLoading(false)
    setError(false)
  }, [])

  const onDocumentLoadError = useCallback(() => {
    setError(true)
    setLoading(false)
  }, [])

  const step = isMobile || !isSpread ? 1 : 2
  const maxPage = Math.max(numPages, 1)

  const goToPrev = useCallback(() => {
    setPageNumber((current) => Math.max(1, current - step))
  }, [step])

  const goToNext = useCallback(() => {
    setPageNumber((current) => Math.min(maxPage, current + step))
  }, [maxPage, step])

  useEffect(() => {
    if (loading || error || isMobile)
      return

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey)
        return

      const activeElement = document.activeElement as HTMLElement | null
      if (activeElement) {
        const tagName = activeElement.tagName
        if (
          activeElement.isContentEditable
          || tagName === 'INPUT'
          || tagName === 'TEXTAREA'
          || tagName === 'SELECT'
        ) {
          return
        }
      }

      if (event.key === 'ArrowLeft') {
        event.preventDefault()
        goToPrev()
      }

      if (event.key === 'ArrowRight') {
        event.preventDefault()
        goToNext()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [error, goToNext, goToPrev, isMobile, loading])

  const toggleFullscreen = useCallback(() => {
    const fullscreenDocument = document as FullscreenCapableDocument
    const viewerShell = viewerShellRef.current as FullscreenCapableElement | null
    const fullscreenElement = getFullscreenElement()

    if (fullscreenElement) {
      if (document.exitFullscreen) {
        void document.exitFullscreen()
      }
      else if (fullscreenDocument.webkitExitFullscreen) {
        fullscreenDocument.webkitExitFullscreen()
      }
      return
    }

    if (!viewerShell)
      return

    if (viewerShell.requestFullscreen) {
      void viewerShell.requestFullscreen()
    }
    else if (viewerShell.webkitRequestFullscreen) {
      viewerShell.webkitRequestFullscreen()
    }
  }, [])

  const rightPage = pageNumber + 1
  const hasRight = isSpread && rightPage <= numPages
  const isNextDisabled = numPages === 0 || pageNumber >= numPages - (step - 1)
  const documentClassName =
    !isMobile && !isSpread
      ? `${styles.document} ${styles.documentSinglePage}`
      : styles.document
  const viewerShellClassName = isFullscreen
    ? `${styles.viewerShell} ${styles.viewerShellFullscreen}`
    : styles.viewerShell
  const keyboardHint = isMobile
    ? 'Scroll to read the full paper.'
    : 'Use ← and → to flip pages.'

  return (
    <div ref={viewerShellRef} className={viewerShellClassName}>
      <div className={styles.viewerToolbar}>
        <div className={styles.viewerToolbarMeta}>
          <span className={styles.viewerHint}>{keyboardHint}</span>
          {!isMobile && !loading && !error && (
            <span className={styles.viewerMode}>
              {isSpread ? 'Spread view' : 'Single-page view'}
            </span>
          )}
        </div>
        {canToggleFullscreen && (
          <button
            type="button"
            className={`${styles.pageBtn} ${styles.toolbarBtn}`}
            onClick={toggleFullscreen}
            aria-label={isFullscreen ? 'Exit fullscreen viewer' : 'Enter fullscreen viewer'}
            aria-pressed={isFullscreen}
          >
            {isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
          </button>
        )}
      </div>

      <div className={styles.viewerArea}>
        {error ? (
          <div className={styles.fallback}>
            <p>Unable to load the PDF preview.</p>
            <a href={PDF_URL} target="_blank" rel="noopener noreferrer">
              Open the PDF in a new tab
            </a>
          </div>
        ) : (
          <Document
            file={PDF_URL}
            onLoadSuccess={onDocumentLoadSuccess}
            onLoadError={onDocumentLoadError}
            loading={<div className={styles.loadingText}>Loading PDF…</div>}
            className={documentClassName}
          >
            {isMobile ? (
              <div className={styles.mobileStack}>
                {Array.from({ length: numPages }, (_, index) => (
                  <div key={index + 1} className={styles.pageWrapper}>
                    <Page
                      pageNumber={index + 1}
                      width={pageWidth}
                      renderTextLayer={true}
                      renderAnnotationLayer={true}
                    />
                  </div>
                ))}
              </div>
            ) : isSpread ? (
              <div className={styles.pagesRow}>
                <div className={styles.pageWrapper}>
                  <Page
                    pageNumber={pageNumber}
                    width={pageWidth}
                    renderTextLayer={true}
                    renderAnnotationLayer={true}
                  />
                </div>
                {hasRight && (
                  <div className={styles.pageWrapper}>
                    <Page
                      pageNumber={rightPage}
                      width={pageWidth}
                      renderTextLayer={true}
                      renderAnnotationLayer={true}
                    />
                  </div>
                )}
              </div>
            ) : (
              <div className={styles.pageWrapper}>
                <Page
                  pageNumber={pageNumber}
                  width={pageWidth}
                  renderTextLayer={true}
                  renderAnnotationLayer={true}
                />
              </div>
            )}
          </Document>
        )}
      </div>

      {!error && !loading && !isMobile && (
        <div className={styles.pagination}>
          <div />
          <div className={styles.paginationCenter}>
            <button
              type="button"
              className={styles.pageBtn}
              onClick={goToPrev}
              disabled={pageNumber <= 1}
              aria-label="Previous page"
            >
              ← Prev
            </button>
            <span className={styles.pageInfo}>
              {pageNumber}
              {hasRight ? `–${rightPage}` : ''}
              {' '}
              /
              {numPages}
            </span>
            <button
              type="button"
              className={styles.pageBtn}
              onClick={goToNext}
              disabled={isNextDisabled}
              aria-label="Next page"
            >
              Next →
            </button>
          </div>
          <div />
        </div>
      )}
    </div>
  )
}

export default function PaperPage(): React.JSX.Element {
  const { siteConfig } = useDocusaurusContext()
  const ogImage = new URL('/assets/brand/social-share-card.png', siteConfig.url).toString()

  return (
    <Layout
      title="Paper"
      description="Elephant Agent: Agency-First Personal AI — full technical paper from Agentic Intelligence Lab."
    >
      <Head>
        <meta property="og:title" content="Paper — Elephant Agent" />
        <meta property="og:description" content="Elephant Agent: Agency-First Personal AI. Full technical paper from Agentic Intelligence Lab, MBZUAI, McGill University, and Mila." />
        <meta property="og:image" content={ogImage} />
        <meta property="og:type" content="article" />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content="Paper — Elephant Agent" />
        <meta name="twitter:description" content="Elephant Agent: Agency-First Personal AI. Full technical paper from Agentic Intelligence Lab." />
        <meta name="twitter:image" content={ogImage} />
      </Head>

      <main className={styles.page}>
        <section className={styles.hero}>
          <div className={styles.heroContent}>
            <span className={styles.heroLabel}>Research</span>
            <h1 className={styles.heroTitle}>Paper</h1>
            <p className={styles.heroDescription}>
              <em>Elephant Agent: Agency-First Personal AI</em>
              <br />
              Personal-Model-First Evolution for Judgment, Evidence, Questions, and Growth
              <br />
              Xunzhuo Liu, Hao Wu, Huamin Chen, Xue Liu, Bowei He
              <br />
              <span className={styles.heroAffiliations}>
                Agentic Intelligence Lab · MBZUAI · McGill University · Mila
              </span>
            </p>
            <div className={styles.heroActions}>
              <a
                href={PDF_URL}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.pill}
              >
                Download PDF
              </a>
              <a
                href="/blog/personal-ai-you-create"
                className={`${styles.pill} ${styles.pillMuted}`}
              >
                Launch Blog
              </a>
            </div>
          </div>
        </section>

        <BrowserOnly
          fallback={(
            <div className={styles.viewerShell}>
              <div className={styles.viewerArea}>
                <div className={styles.loadingText}>Loading PDF…</div>
              </div>
            </div>
          )}
        >
          {() => <PaperViewerContent />}
        </BrowserOnly>
      </main>
    </Layout>
  )
}
