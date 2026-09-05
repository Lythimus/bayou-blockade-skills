--[[
  bayou-filing.lua — maps fenced divs in the filing markdown onto the callout
  environments defined in bayou-filing.tex.

      ::: comment          →  \begin{filingcomment} … \end{filingcomment}
      ::: recordquote      →  \begin{filingrecordquote} … \end{filingrecordquote}
      ::: alert            →  \begin{filingalert} … \end{filingalert}

  Why a filter instead of styling blockquotes: the filing quotes the agency's
  own record constantly, so `>` has to keep meaning "quotation." Overloading it
  to also mean "requested permit condition" would make the two indistinguishable
  in exactly the document where the distinction matters most.

  Non-LaTeX output (e.g. the plain .md a user emails, or an HTML preview) passes
  through untouched — the div contents still render, just without the frame.
]]

local environments = {
  comment     = 'filingcomment',
  recordquote = 'filingrecordquote',
  alert       = 'filingalert',
}

function Div (el)
  if not FORMAT:match('latex') then
    return nil
  end

  for _, class in ipairs(el.classes) do
    local env = environments[class]
    if env then
      local blocks = pandoc.List()
      blocks:insert(pandoc.RawBlock('latex', '\\begin{' .. env .. '}'))
      blocks:extend(el.content)
      blocks:insert(pandoc.RawBlock('latex', '\\end{' .. env .. '}'))
      return blocks
    end
  end

  return nil
end
