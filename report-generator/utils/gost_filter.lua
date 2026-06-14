-- Pandoc Lua filter for GOST .docx output
local figure_counter = 0

function Pandoc(doc)
  local meta = doc.meta
  local blocks = doc.blocks

  local function get_string(value, default)
    if value == nil then
      return default or ''
    end
    if type(value) == 'table' then
      return pandoc.utils.stringify(value)
    end
    return tostring(value)
  end

  local function get_bool(value, default)
    if value == nil then return default or false end
    if type(value) == 'boolean' then return value end
    local s = tostring(value):lower()
    return s == 'true' or s == 'yes' or s == '1'
  end

  local function escape_xml(text)
    return tostring(text)
      :gsub('&', '&amp;')
      :gsub('<', '&lt;')
      :gsub('>', '&gt;')
  end

  local function cxml(text, align, bold, size)
    local safe_text = escape_xml(text)
    local jc = (align == 'r') and '<w:jc w:val="right"/>' or '<w:jc w:val="center"/>'
    local b = bold and '<w:b/>' or ''
    local sz = 28
    if size then
      sz = math.floor(tonumber(size) * 2)
    end
    return '<w:p><w:pPr>'..jc..'<w:ind w:firstLine="0"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/><w:sz w:val="'..sz..'"/>'..b..'</w:rPr><w:t xml:space="preserve">'..safe_text..'</w:t></w:r></w:p>'
  end

  local function render_cover_line(line)
    if not line then
      return nil
    end
    if line.spacer then
      return '<w:p/>'
    end
    local text = get_string(line.text, '')
    local align = get_string(line.align, 'c')
    local bold = get_bool(line.bold, false)
    local size = tonumber(line.size) or 14
    return cxml(text, align, bold, size)
  end

  local function render_default_cover(meta)
    local inst = get_string(meta.institution, '')
    local label = get_string(meta.report_label, '')
    local theme = get_string(meta.title, '')
    local spec = get_string(meta.specialty, '')
    local author = get_string(meta.author, '')
    local grp = get_string(meta.group, '')
    local adv_name = get_string(meta.advisor_name, '')
    local adv_pos = get_string(meta.advisor_position, '')
    local inst_short = get_string(meta.institution_short, '')
    local year = get_string(meta.date, '')

    return {
      cxml(inst, 'c', true, 14), '<w:p/>', '<w:p/>',
      cxml(label, 'c', true, 14), '<w:p/>',
      cxml(theme, 'c', true, 14),
      cxml('по направлению подготовки «'..spec..'»', 'c', false, 14),
      '<w:p/>', '<w:p/>',
      cxml('Студент:', 'r', false, 14),
      cxml('    '..author, 'r', false, 14),
      cxml('    Группа '..grp, 'r', false, 14), '<w:p/>',
      cxml('Руководитель практики:', 'r', false, 14),
      cxml('    '..adv_name, 'r', false, 14), '<w:p/>',
      cxml('    '..adv_pos, 'r', false, 14), '<w:p/>', '<w:p/>',
      cxml(inst_short..' – '..year, 'c', false, 14),
      '<w:p><w:r><w:br w:type="page"/></w:r></w:p>',
    }
  end

  local cover = {}
  local cover_meta = meta.cover_page
  if cover_meta and cover_meta.header_lines then
    for i = 1, #cover_meta.header_lines do
      local entry = cover_meta.header_lines[i]
      local block = render_cover_line(entry)
      if block then
        table.insert(cover, block)
      end
    end
    table.insert(cover, '<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
  else
    cover = render_default_cover(meta)
  end

  for i = #cover, 1, -1 do
    table.insert(blocks, 1, pandoc.RawBlock('openxml', cover[i]))
  end
  return pandoc.Pandoc(blocks, meta)
end

function Image(img)
  if img.caption and #img.caption > 0 then
    figure_counter = figure_counter + 1
    local prefix = pandoc.Str('Рисунок '..figure_counter..'. ')
    img.caption = pandoc.List({prefix})..img.caption
  end
  return img
end

return {{Pandoc = Pandoc}, {Image = Image}}
