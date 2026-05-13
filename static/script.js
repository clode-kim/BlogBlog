'use strict';

// ─── State ───────────────────────────────────────────────────────────────────
let selectedFiles = [];
let generatedPost = '';
let kwIdCounter = 0;

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const uploadZone    = document.getElementById('uploadZone');
const fileInput     = document.getElementById('fileInput');
const imageGrid     = document.getElementById('imageGrid');
const blogIdInput   = document.getElementById('blogIdInput');
const blogIdPreview = document.getElementById('blogIdPreview');
const verifyBtn     = document.getElementById('verifyBtn');
const blogStatus    = document.getElementById('blogStatus');
const guideInput    = document.getElementById('guideInput');
const keywordList   = document.getElementById('keywordList');
const addKeywordBtn = document.getElementById('addKeywordBtn');
const generateBtn   = document.getElementById('generateBtn');

const stateEmpty   = document.getElementById('stateEmpty');
const stateLoading = document.getElementById('stateLoading');
const stateError   = document.getElementById('stateError');
const stateResult  = document.getElementById('stateResult');
const errorMessage = document.getElementById('errorMessage');

const imageAnalysisArea = document.getElementById('imageAnalysisArea');
const analysisContent   = document.getElementById('analysisContent');
const analysisIcon      = document.getElementById('analysisIcon');
const styleWarning      = document.getElementById('styleWarning');
const keywordCheckArea = document.getElementById('keywordCheckArea');
const kwBadges         = document.getElementById('kwBadges');
const titleArea        = document.getElementById('titleArea');
const titleList        = document.getElementById('titleList');
const charCount        = document.getElementById('charCount');
const postDisplay      = document.getElementById('postDisplay');
const copyBtn          = document.getElementById('copyBtn');
const regenerateBtn    = document.getElementById('regenerateBtn');

// ─── Image Upload ─────────────────────────────────────────────────────────────
uploadZone.addEventListener('click', () => fileInput.click());

uploadZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  uploadZone.classList.add('drag-over');
});

uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));

uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadZone.classList.remove('drag-over');
  const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
  addFiles(files);
});

fileInput.addEventListener('change', () => {
  addFiles(Array.from(fileInput.files));
  fileInput.value = '';
});

function addFiles(files) {
  files.forEach(async file => {
    const isDupe = selectedFiles.some(f => f.name === file.name && f.size === file.size);
    if (!isDupe) {
      try {
        // 이미지 압축 처리
        const compressedFile = await compressImage(file);
        selectedFiles.push(compressedFile);
      } catch (error) {
        console.error('이미지 압축 실패:', error);
        // 압축 실패 시 원본 파일 사용 (크기 검증은 유지)
        if (file.size > 5 * 1024 * 1024) {
          alert(`파일 "${file.name}"이 너무 큽니다. 5MB 이하의 파일만 업로드 가능합니다.`);
          return;
        }
        selectedFiles.push(file);
      }
    }
  });
  renderImageGrid();
}

// 이미지 압축 함수
async function compressImage(file) {
  return new Promise((resolve, reject) => {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const img = new Image();

    img.onload = () => {
      // 최대 크기 설정 (1920px)
      const maxWidth = 1920;
      const maxHeight = 1920;

      let { width, height } = img;

      // 크기 조정
      if (width > height) {
        if (width > maxWidth) {
          height = (height * maxWidth) / width;
          width = maxWidth;
        }
      } else {
        if (height > maxHeight) {
          width = (width * maxHeight) / height;
          height = maxHeight;
        }
      }

      canvas.width = width;
      canvas.height = height;

      // 이미지 그리기
      ctx.drawImage(img, 0, 0, width, height);

      // 압축된 이미지로 변환
      canvas.toBlob((blob) => {
        const compressedFile = new File([blob], file.name, {
          type: file.type,
          lastModified: Date.now()
        });
        resolve(compressedFile);
      }, file.type, 0.8); // 80% 품질
    };

    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}

function removeFile(index) {
  selectedFiles.splice(index, 1);
  renderImageGrid();
}

function renderImageGrid() {
  imageGrid.innerHTML = '';
  selectedFiles.forEach((file, i) => {
    const wrap = document.createElement('div');
    wrap.className = 'image-thumb';

    const img = document.createElement('img');
    img.src = URL.createObjectURL(file);
    img.alt = file.name;

    const btn = document.createElement('button');
    btn.className = 'remove-img';
    btn.innerHTML = '×';
    btn.title = '삭제';
    btn.onclick = (e) => { e.stopPropagation(); removeFile(i); };

    wrap.appendChild(img);
    wrap.appendChild(btn);
    imageGrid.appendChild(wrap);
  });
}

// ─── Blog ID preview ──────────────────────────────────────────────────────────
blogIdInput.addEventListener('input', () => {
  blogIdPreview.textContent = blogIdInput.value.trim() || 'ID';
  blogStatus.style.display = 'none';
});

// ─── Blog Verify ─────────────────────────────────────────────────────────────
verifyBtn.addEventListener('click', async () => {
  const blogId = blogIdInput.value.trim();
  if (!blogId) { showBlogStatus('블로그 ID를 입력해주세요.', 'error'); return; }

  verifyBtn.disabled = true;
  verifyBtn.textContent = '확인 중...';
  blogStatus.style.display = 'none';

  try {
    const res = await fetch('/api/fetch-blog-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ blog_id: blogId })
    });
    const data = await res.json();

    if (data.success) {
      const titles = data.posts.map(p => `• ${p.title}`).join('\n');
      showBlogStatus(`✓ 연결 성공! 최근 ${data.count}개 글을 참고합니다.\n${titles}`, 'success');
    } else {
      showBlogStatus(`✗ ${data.error}`, 'error');
    }
  } catch {
    showBlogStatus('블로그 확인 중 오류가 발생했습니다.', 'error');
  } finally {
    verifyBtn.disabled = false;
    verifyBtn.textContent = '확인';
  }
});

function showBlogStatus(msg, type) {
  blogStatus.textContent = msg;
  blogStatus.className = `blog-status ${type}`;
  blogStatus.style.display = 'block';
}

// ─── Keywords ─────────────────────────────────────────────────────────────────
addKeywordBtn.addEventListener('click', addKeywordRow);

function addKeywordRow() {
  kwIdCounter++;
  const id = kwIdCounter;

  const row = document.createElement('div');
  row.className = 'keyword-row';
  row.dataset.kwid = id;
  row.innerHTML = `
    <input type="text" class="kw-text-input" placeholder="키워드 입력" />
    <input type="number" class="kw-count-input" min="1" max="30" value="3" />
    <span class="kw-unit">회 이상</span>
    <button class="kw-remove" onclick="removeKeywordRow(${id})">×</button>
  `;
  keywordList.appendChild(row);
}

function removeKeywordRow(id) {
  const row = keywordList.querySelector(`[data-kwid="${id}"]`);
  if (row) row.remove();
}

function collectKeywords() {
  return Array.from(keywordList.querySelectorAll('.keyword-row'))
    .map(row => ({
      keyword: row.querySelector('.kw-text-input').value.trim(),
      count: parseInt(row.querySelector('.kw-count-input').value) || 1
    }))
    .filter(kw => kw.keyword);
}

// ─── Generate ─────────────────────────────────────────────────────────────────
generateBtn.addEventListener('click', generate);
regenerateBtn.addEventListener('click', generate);

async function generate() {
  if (selectedFiles.length === 0) {
    alert('이미지를 최소 1개 이상 업로드해주세요.');
    return;
  }

  showState('loading');
  generateBtn.disabled = true;

  try {
    const formData = new FormData();
    selectedFiles.forEach(f => formData.append('images', f));
    formData.append('blog_id', blogIdInput.value.trim());
    formData.append('guide', guideInput.value.trim());
    formData.append('keywords', JSON.stringify(collectKeywords()));
    formData.append('min_chars', document.getElementById('minCharInput').value.trim());
    formData.append('title_keywords', document.getElementById('titleKeywordsInput').value.trim());
    const coupangToggle = document.getElementById('coupangToggle');
    formData.append('use_coupang', coupangToggle.checked ? 'true' : 'false');
    formData.append('coupang_count', document.getElementById('coupangCount').value);

    const res = await fetch('/api/generate', { method: 'POST', body: formData });
    const text = await res.text();

    let data;
    try {
      data = JSON.parse(text);
    } catch (e) {
      throw new Error(`서버 응답을 파싱할 수 없습니다. 상태 ${res.status}: ${res.statusText}\n응답 본문: ${text}`);
    }

    if (!res.ok) {
      throw new Error(data.error || `서버 오류가 발생했습니다. 상태 ${res.status}`);
    }

    if (data.success) {
      generatedPost = data.post;
      renderResult(data);
    } else {
      showState('error', data.error || '알 수 없는 오류가 발생했습니다.');
    }
  } catch (error) {
    console.error('Generate error:', error);
    showState('error', error.message || '네트워크 오류가 발생했습니다. 다시 시도해주세요.');
  } finally {
    generateBtn.disabled = false;
  }
}

function renderResult(data) {
  // Style warning
  if (data.style_error || data.keyword_reference_error) {
    const warnings = [];
    if (data.style_error) warnings.push(data.style_error + ' (스타일 참고 없이 글을 생성했습니다)');
    if (data.keyword_reference_error) warnings.push(data.keyword_reference_error + ' (키워드 기반 참고 검색에 실패했습니다)');
    styleWarning.textContent = `⚠️ ${warnings.join(' | ')}`;
    styleWarning.style.display = 'block';
  } else {
    styleWarning.style.display = 'none';
  }

  // Keyword check badges
  const kwCheck = data.keyword_check || {};
  const kwKeys = Object.keys(kwCheck);
  if (kwKeys.length > 0) {
    kwBadges.innerHTML = kwKeys.map(kw => {
      const info = kwCheck[kw];
      const cls = info.satisfied ? 'ok' : 'fail';
      const icon = info.satisfied ? '✓' : '✗';
      return `<span class="kw-badge ${cls}">${icon} "${kw}" ${info.actual}/${info.required}회</span>`;
    }).join('');
    keywordCheckArea.style.display = 'block';
  } else {
    keywordCheckArea.style.display = 'none';
  }

  // 이미지 분석 결과
  if (data.image_analysis) {
    analysisContent.textContent = data.image_analysis;
    imageAnalysisArea.style.display = 'block';
    analysisContent.style.display = 'none';
    analysisIcon.textContent = '▼ 펼치기';
  } else {
    imageAnalysisArea.style.display = 'none';
  }

  // 글자수 표시
  if (data.char_count !== undefined) {
    charCount.textContent = `공백 제외 ${data.char_count.toLocaleString()}자 · 전체 ${data.char_count_total.toLocaleString()}자`;
  }

  // SEO 제목 추천
  if (data.titles && data.titles.length > 0) {
    titleList.innerHTML = data.titles.map((t, i) => `
      <button class="title-item" onclick="copyTitle(this, ${JSON.stringify(t)})">
        <span class="title-num">${i + 1}</span>
        <span>${t}</span>
        <span class="title-copied">✓ 복사됨</span>
      </button>
    `).join('');
    titleArea.style.display = 'block';
  } else {
    titleArea.style.display = 'none';
  }

  // 쿠팡 상품 파싱 맵 (태그 → 카드 HTML)
  const coupangMap = {};
  (data.coupang_products || []).forEach(p => {
    coupangMap[p.name.substring(0, 20)] = p;
  });

  const escaped = data.post
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // {{COUPANG:이름:가격:url}} 태그를 카드로 변환
  const withCoupang = escaped.replace(
    /\{\{COUPANG:([^:}]+):([^:}]*):([^}]+)\}\}/g,
    (_, name, price, url) => `
      <a href="${url}" target="_blank" rel="noopener" class="coupang-product-card">
        <div class="coupang-product-info">
          <div class="coupang-product-name">${name}</div>
          ${price ? `<div class="coupang-product-price">${price}</div>` : ''}
        </div>
        <span class="coupang-badge">쿠팡 보기 →</span>
      </a>`
  );

  const withImageTags = withCoupang.replace(
    /\[이미지\s*(\d+)\]/g,
    '<span class="img-placeholder">🖼️ 이미지 $1</span>'
  );

  postDisplay.innerHTML = withImageTags.replace(/\n/g, '<br>');
  showState('result');
}

// ─── Copy ─────────────────────────────────────────────────────────────────────
copyBtn.addEventListener('click', async () => {
  if (!generatedPost) return;
  try {
    await navigator.clipboard.writeText(generatedPost);
  } catch {
    // fallback: clipboard API 미지원 환경
  }
  copyBtn.textContent = '✓ 복사됨!';
  setTimeout(() => { copyBtn.textContent = '📋 복사'; }, 2000);
});

// ─── Coupang toggle ───────────────────────────────────────────────────────────
document.getElementById('coupangToggle').addEventListener('change', function () {
  document.getElementById('coupangOptions').style.display = this.checked ? 'block' : 'none';
});

// ─── Analysis toggle ──────────────────────────────────────────────────────────
function toggleAnalysis() {
  const isHidden = analysisContent.style.display === 'none';
  analysisContent.style.display = isHidden ? 'block' : 'none';
  analysisIcon.textContent = isHidden ? '▲ 접기' : '▼ 펼치기';
}

// ─── Title copy ───────────────────────────────────────────────────────────────
async function copyTitle(el, text) {
  try {
    await navigator.clipboard.writeText(text);
    el.classList.add('copied');
    setTimeout(() => el.classList.remove('copied'), 2000);
  } catch {}
}

// ─── State machine ────────────────────────────────────────────────────────────
function showState(state, errMsg) {
  stateEmpty.style.display   = state === 'empty'   ? 'flex' : 'none';
  stateLoading.style.display = state === 'loading' ? 'flex' : 'none';
  stateError.style.display   = state === 'error'   ? 'flex' : 'none';
  stateResult.style.display  = state === 'result'  ? 'block' : 'none';

  if (state === 'error' && errMsg) errorMessage.textContent = errMsg;
}
