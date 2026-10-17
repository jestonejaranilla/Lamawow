(function(){
  /* the department name in the banner comes from the department's file (main-script.js) */

  /* mobile-friendly input hints */
  function enh(){
    document.querySelectorAll('input[type=number]').forEach(function(i){if(!i.hasAttribute('inputmode')){i.setAttribute('inputmode','decimal');i.setAttribute('enterkeyhint','done');}});
    document.querySelectorAll('#facultyTable td:first-child input[type=text], #subjectsTable .subject-name').forEach(function(i){if(!i.hasAttribute('autocapitalize')){i.setAttribute('autocapitalize','words');i.setAttribute('autocomplete','off');i.setAttribute('enterkeyhint','next');}});
  }
  enh();
  var m=document.querySelector('main');
  if(m)new MutationObserver(enh).observe(m,{childList:true,subtree:true});

  /* long result lists collapse into named dropdowns on mobile */
(function(){
  var mq=window.matchMedia('(max-width:768px)');
  function rows(el){return Array.prototype.filter.call(el.querySelectorAll('tbody tr'),function(r){return !r.querySelector('td[colspan]');}).length;}
  function sel(q){return function(el){return el.querySelectorAll(q).length;};}
  function byId(id){return function(){return document.getElementById(id);};}
  function parentOf(id){return function(){var e=document.getElementById(id);return e?e.parentElement:null;};}
  var C=[
    {find:byId('dashboardFacultyAssignments'),title:'Faculty Assignments',count:sel('.fac-assign-card')},
    {find:byId('gaTableWrapper'),title:'Assignments',count:rows},
    {find:byId('fairnessPerFaculty'),title:'Faculty Fairness',count:rows},
    {find:parentOf('roomUtilCapTable'),title:'Room Utilization',count:rows},
    {find:parentOf('capacityDetailsTable'),title:'Capacity Details',count:rows},
    {find:byId('reportsSummaryGrid'),title:'Faculty Summaries',count:sel('.summary-faculty-card')},
    {find:parentOf('facultyTable'),title:'Faculty List',count:rows,add:'addFacultyRow'},
    {find:parentOf('subjectsTable'),title:'Subjects List',count:rows,add:'addSubjectRow'},
    {find:parentOf('classSizesTable'),title:'Class Sections',count:rows,add:'addClassSizeRow'},
    {find:byId('lectureRoomsList'),title:'Lecture Rooms',count:sel('.room-item'),add:'addLectureRoom',partner:true},
    {find:byId('labRoomsList'),title:'Laboratory Rooms',count:sel('.room-item'),add:'addLabRoom',partner:true}
  ];
  var openGroups={},raf=0;
  function setup(){
    C.forEach(function(it){
      if(it.el)return;
      var el=it.find();
      if(!el)return;
      it.el=el;
      var pt=null;
      if(it.partner&&el.previousElementSibling&&el.previousElementSibling.classList.contains('room-cap-col-labels'))pt=el.previousElementSibling;
      it.pt=pt;
      var b=document.createElement('button');
      b.type='button';b.className='m-acc';b.setAttribute('aria-expanded','false');b.hidden=true;
      b.innerHTML='<span class="m-acc-title"></span><span class="m-acc-count"></span><span class="m-acc-chev" aria-hidden="true"></span>';
      b.firstChild.textContent=it.title;
      it.hdr=b;it.cnt=b.children[1];
      (pt||el).parentNode.insertBefore(b,pt||el);
      b.addEventListener('click',function(){it.open=!it.open;refresh();});
      if(it.add){var a=document.getElementById(it.add);if(a)a.addEventListener('click',function(){it.open=true;refresh();});}
    });
  }
  function refresh(){
    setup();
    C.forEach(function(it){
      if(!it.el)return;
      var n=it.count(it.el),hide=n===0||it.el.classList.contains('hidden'),closed=!hide&&!it.open;
      var t=String(n);
      if(it.cnt.textContent!==t)it.cnt.textContent=t;
      it.hdr.hidden=hide;
      it.hdr.setAttribute('aria-expanded',it.open?'true':'false');
      it.el.classList.toggle('m-closed',closed);
      if(it.pt)it.pt.classList.toggle('m-closed',closed);
    });
    document.querySelectorAll('#subjectsContainer .curriculum-group').forEach(function(g){
      var h=g.querySelector('.curriculum-header');if(!h)return;
      var n=String(rows(g));
      if(h.getAttribute('data-count')!==n)h.setAttribute('data-count',n);
      g.classList.toggle('open',!!openGroups[h.firstChild?h.firstChild.textContent.trim():'']);
    });
  }
  function sched(){if(!raf)raf=requestAnimationFrame(function(){raf=0;refresh();});}
  var sc=document.getElementById('subjectsContainer');
  if(sc)sc.addEventListener('click',function(e){
    var h=e.target.closest('.curriculum-header');if(!h||!mq.matches)return;
    var k=h.firstChild?h.firstChild.textContent.trim():'';
    openGroups[k]=!openGroups[k];refresh();
  });
  var m=document.querySelector('main');
  if(m)new MutationObserver(sched).observe(m,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});
  if(mq.addEventListener)mq.addEventListener('change',sched);
  refresh();
})();
})();

/* CSP: no inline handlers in the page */
(function () {
  var b = document.getElementById('goToAdvancedSettings');
  if (b) b.addEventListener('click', function () { window.location.href = '../app/application-settings.html#solver'; });
})();