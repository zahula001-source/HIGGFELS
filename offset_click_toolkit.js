/**
 * PLAYWRIGHT OFFSET CLICKER TOOLKIT
 * Hướng dẫn sử dụng:
 * 1. Mở trang web cần lấy tọa độ click.
 * 2. Mở DevTools (F12) -> Console.
 * 3. Nếu nút nằm trong iframe, nhớ chọn đúng context Iframe trong Console (danh sách dropdown chữ 'top').
 * 4. Copy toàn bộ đoạn code này, dán vào Console và nhấn Enter.
 * 5. Bảng điều khiển sẽ hiện ra ở góc phải dưới màn hình.
 */

(function () {
  if (document.getElementById("dola-toolkit-panel")) {
    console.log("Toolkit đã được tải rồi!");
    return;
  }

  // Khởi tạo các phần tử UI
  const panel = document.createElement("div");
  panel.id = "dola-toolkit-panel";
  Object.assign(panel.style, {
    position: "fixed",
    bottom: "20px",
    right: "20px",
    width: "320px",
    backgroundColor: "#1e1e1e",
    color: "#d4d4d4",
    fontFamily: "monospace",
    fontSize: "13px",
    padding: "15px",
    borderRadius: "8px",
    boxShadow: "0 4px 20px rgba(0,0,0,0.8)",
    zIndex: "2147483647",
    border: "1px solid #333",
  });

  panel.innerHTML = `
    <div style="font-weight:bold; color:#4fc1ff; margin-bottom:10px; font-size:15px; text-align:center;">
      🎯 OFFSET CLICK TOOLKIT
    </div>
    
    <label style="display:block; margin-bottom:5px;">Neo (Selector):</label>
    <input type="text" id="tk-selector" value="img.icon-ieQdCp" style="width:100%; padding:5px; background:#252526; color:#fff; border:1px solid #3c3c3c; margin-bottom:10px; box-sizing:border-box;" />

    <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
      <div style="width: 48%;">
        <label>Offset X (px):</label>
        <input type="number" id="tk-offset-x" value="0" style="width:100%; padding:5px; background:#252526; color:#fff; border:1px solid #3c3c3c; box-sizing:border-box;" />
      </div>
      <div style="width: 48%;">
        <label>Offset Y (px):</label>
        <input type="number" id="tk-offset-y" value="30" style="width:100%; padding:5px; background:#252526; color:#fff; border:1px solid #3c3c3c; box-sizing:border-box;" />
      </div>
    </div>

    <label style="display:block; margin-bottom:5px;">Size (Khung đỏ - px):</label>
    <input type="number" id="tk-size" value="50" style="width:100%; padding:5px; background:#252526; color:#fff; border:1px solid #3c3c3c; margin-bottom:10px; box-sizing:border-box;" />

    <div style="font-size: 11px; color:#858585; margin-bottom: 10px;">
      💡 Tip: Click chuột vào một trong các ô Offset, sau đó dùng phím mũi tên (lên/xuống/trái/phải) để di chuyển viền đỏ thật mượt!
    </div>

    <button id="tk-test-btn" style="width:100%; padding:8px; background:#0e639c; color:white; border:none; border-radius:4px; cursor:pointer; margin-bottom:10px; font-weight:bold;">
      🧪 TEST CLICK
    </button>
    
    <button id="tk-code-btn" style="width:100%; padding:8px; background:#16825d; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:bold;">
      📋 COPY PLAYWRIGHT PYTHON CODE
    </button>
  `;

  document.body.appendChild(panel);

  const selInput = document.getElementById("tk-selector");
  const oxInput = document.getElementById("tk-offset-x");
  const oyInput = document.getElementById("tk-offset-y");
  const sizeInput = document.getElementById("tk-size");

  let square = null;

  // Cập nhật vị trí ô đỏ liên tục
  function updateHighlight() {
    const selector = selInput.value.trim();
    if (!selector) return;

    const anchor = document.querySelector(selector);
    if (!anchor) {
      if (square) { square.remove(); square = null; }
      return;
    }

    const r = anchor.getBoundingClientRect();
    const ox = parseFloat(oxInput.value) || 0;
    const oy = parseFloat(oyInput.value) || 0;
    const size = parseFloat(sizeInput.value) || 50;

    // Tính toán từ điểm chính giữa cạnh dưới của Neo
    const startX = r.left + r.width / 2;
    const startY = r.bottom;

    const x = startX - (size / 2) + ox;
    const y = startY + oy;

    if (!square) {
      square = document.createElement("div");
      square.id = "tk-live-highlight";
      Object.assign(square.style, {
        position: "fixed",
        boxSizing: "border-box",
        border: "4px solid #ff0033",
        borderRadius: "4px",
        background: "rgba(255, 0, 51, .18)",
        boxShadow: "0 0 18px 7px rgba(255, 0, 51, .75)",
        zIndex: "2147483647",
        pointerEvents: "none"
      });
      document.body.appendChild(square);
    }

    square.style.left = `${x}px`;
    square.style.top = `${y}px`;
    square.style.width = `${size}px`;
    square.style.height = `${size}px`;
  }

  // Lắng nghe sự kiện phím mũi tên
  document.addEventListener("keydown", (e) => {
    if (document.activeElement !== oxInput && document.activeElement !== oyInput) return;
    
    if (e.key === "ArrowUp") {
      oyInput.value = (parseFloat(oyInput.value) || 0) - 1;
      updateHighlight();
      e.preventDefault();
    } else if (e.key === "ArrowDown") {
      oyInput.value = (parseFloat(oyInput.value) || 0) + 1;
      updateHighlight();
      e.preventDefault();
    } else if (e.key === "ArrowLeft") {
      oxInput.value = (parseFloat(oxInput.value) || 0) - 1;
      updateHighlight();
      e.preventDefault();
    } else if (e.key === "ArrowRight") {
      oxInput.value = (parseFloat(oxInput.value) || 0) + 1;
      updateHighlight();
      e.preventDefault();
    }
  });

  selInput.addEventListener("input", updateHighlight);
  oxInput.addEventListener("input", updateHighlight);
  oyInput.addEventListener("input", updateHighlight);
  sizeInput.addEventListener("input", updateHighlight);

  setInterval(updateHighlight, 500);

  // Test Click Logic
  document.getElementById("tk-test-btn").addEventListener("click", async () => {
    if (!square) return alert("Không tìm thấy Điểm neo (Selector)!");

    const x = parseFloat(square.style.left);
    const y = parseFloat(square.style.top);
    const size = parseFloat(square.style.width);

    // Ẩn để chọc xuyên
    square.style.display = "none";
    const target = document.elementFromPoint(x + size / 2, y + size / 2);
    square.style.display = "block";

    if (!target) return alert("Không tìm thấy phần tử nào tại tâm ô vuông!");

    const clickable = target.closest("button, a, [role='button'], [onclick], .confirm-button-ZuDQ59") || target;
    console.log("Đã tìm thấy phần tử:", clickable);
    
    clickable.dispatchEvent(new PointerEvent("pointerover", { bubbles: true, view: window }));
    clickable.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, view: window }));
    clickable.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, view: window }));
    await new Promise(r => setTimeout(r, 100));
    clickable.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, view: window }));
    clickable.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, view: window }));
    clickable.click();
    
    alert("Đã click thành công! Xem log Console để biết phần tử.");
  });

  // Generate Playwright Code
  document.getElementById("tk-code-btn").addEventListener("click", () => {
    const s = selInput.value.trim();
    const ox = parseFloat(oxInput.value) || 0;
    const oy = parseFloat(oyInput.value) || 0;
    const size = parseFloat(sizeInput.value) || 50;

    const pythonCode = `                # Bấm phần tử bằng Toolkit Offset Clicker
                success = False
                for attempt in range(5):
                    page.wait_for_timeout(2000)
                    
                    js_code = """
                        async () => {
                            const anchor = document.querySelector("${s}");
                            if (!anchor) return "KhongThayNeo";

                            const r = anchor.getBoundingClientRect();
                            const size = ${size};
                            
                            // Toạ độ tính từ điểm chính giữa đáy của anchor
                            const startX = r.left + r.width / 2;
                            const startY = r.bottom;

                            const x = startX - (size / 2) + (${ox});
                            const y = startY + (${oy});

                            // Xoá overlay cũ nếu có
                            document.getElementById("tk-highlight-bot")?.remove();
                            const square = document.createElement("div");
                            square.id = "tk-highlight-bot";
                            Object.assign(square.style, {
                                position: "fixed", left: \\\`\${x}px\\\`, top: \\\`\${y}px\\\`, width: \\\`\${size}px\\\`, height: \\\`\${size}px\\\`,
                                boxSizing: "border-box", border: "4px solid #ff0033", borderRadius: "4px",
                                background: "rgba(255, 0, 51, .18)", boxShadow: "0 0 18px 7px rgba(255, 0, 51, .75)",
                                zIndex: "2147483647", pointerEvents: "none"
                            });
                            document.body.appendChild(square);
                            
                            await new Promise(resolve => setTimeout(resolve, 1000));
                            
                            square.style.display = "none";
                            const target = document.elementFromPoint(x + size / 2, y + size / 2);
                            square.remove();

                            if (!target) return "KhongCoPhanTu";

                            const clickable = target.closest("button, a, [role='button'], [onclick], .confirm-button-ZuDQ59") || target;
                            clickable.click();
                            return "DaClick";
                        }
                    """
                    
                    clicked_this_round = False
                    for f in page.frames:
                        try:
                            result = f.evaluate(js_code)
                            if result == "DaClick":
                                print(f"     -> [Tuyệt vời] Đã vẽ highlight và CLICK TRÚNG ĐÍCH trong frame: {f.name or f.url}")
                                clicked_this_round = True
                                break
                        except Exception: pass
                            
                    if clicked_this_round:
                        success = True
                        break
`;

    const el = document.createElement('textarea');
    el.value = pythonCode;
    document.body.appendChild(el);
    el.select();
    document.execCommand('copy');
    document.body.removeChild(el);

    const btn = document.getElementById("tk-code-btn");
    btn.innerText = "✅ ĐÃ COPY PYTHON CODE!";
    btn.style.background = "#095c40";
    setTimeout(() => {
      btn.innerText = "📋 COPY PLAYWRIGHT PYTHON CODE";
      btn.style.background = "#16825d";
    }, 2000);
  });
})();
