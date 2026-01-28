# Build FULL FINAL REPORT: black KPI tiles, white text, black icons, ALL pages restored

import pandas as pd, numpy as np, matplotlib.pyplot as plt, os
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, Flowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

# ---------- Load Data ----------
path="/mnt/data/sales-detail-x-8884389-from-2025-Jan-01-to-2025-Dec-31-on-2026-Jan-27.csv"
df=pd.read_csv(path)

def parse_money(s):
    if pd.isna(s): return 0.0
    s=str(s).replace('$','').replace(',','').strip()
    if s.startswith('(') and s.endswith(')'):
        s='-'+s[1:-1]
    try: return float(s)
    except: return 0.0

for c in ['Ext Item Price','Ext Item Total','Ext Item Taxes','Ext Item Shipping']:
    if c in df.columns:
        df[c]=df[c].apply(parse_money)

df['Quantity Sold']=pd.to_numeric(df['Quantity Sold'], errors='coerce').fillna(0)
df['Completed Date']=pd.to_datetime(df['Completed Date'], errors='coerce')
df['Pickup']=df['Pickup'].astype(str).str.lower().isin(['yes','true','1'])

orders=df.groupby('Order Number').agg(
    completed_date=('Completed Date','first'),
    order_type=('Order Type','first'),
    ship_state=('Ship State Code','first'),
    customer=('Customer Number','first'),
    pickup=('Pickup','first'),
    units=('Quantity Sold','sum'),
    net_sales=('Ext Item Price','sum'),
    order_total=('Ext Item Total','sum'),
    taxes=('Ext Item Taxes','sum'),
    shipping_paid=('Ext Item Shipping','sum')
).reset_index()

# ---------- KPI Calculations ----------
total_orders=len(orders)
total_units=float(orders['units'].sum())
net_sales=float(orders['net_sales'].sum())
order_total=float(orders['order_total'].sum())
taxes=float(orders['taxes'].sum())
aov=net_sales/total_orders
avg_bottle_price=net_sales/total_units

cust_orders=orders.dropna(subset=['customer'])
unique_customers=int(cust_orders['customer'].nunique())
repeat_customers=int((cust_orders.groupby('customer')['Order Number'].nunique()>1).sum())
repeat_rate=repeat_customers/unique_customers
avg_bottles_per_customer=cust_orders.groupby('customer')['units'].sum().mean()

pickup_count=int((orders['pickup']==True).sum())
shipping_count=int((orders['pickup']==False).sum())

orders['month']=orders['completed_date'].dt.to_period('M').dt.to_timestamp()
monthly=orders.groupby('month').agg(net_sales=('net_sales','sum'),orders=('Order Number','count'),units=('units','sum')).reset_index()

peak_row=monthly.loc[monthly['net_sales'].idxmax()]
low_row=monthly.loc[monthly['net_sales'].idxmin()]

# ---------- Charts ----------
out_dir="/mnt/data/report_assets"
os.makedirs(out_dir, exist_ok=True)

def save_fig(name):
    fp=os.path.join(out_dir,name)
    plt.tight_layout()
    plt.savefig(fp,dpi=200,bbox_inches='tight')
    plt.close()
    return fp

plt.figure(figsize=(10,4))
plt.plot(monthly['month'],monthly['net_sales'],marker='o')
plt.title("Monthly Net Sales - 2025")
plt.xlabel("Month"); plt.ylabel("Net Sales ($)")
save_fig("monthly_net_sales.png")

plt.figure(figsize=(10,4))
plt.plot(monthly['month'],monthly['orders'],marker='o',label="Orders")
plt.plot(monthly['month'],monthly['units'],marker='o',label="Units")
plt.legend(); plt.title("Monthly Orders & Units - 2025")
save_fig("monthly_orders_units.png")

by_channel=orders.groupby('order_type').agg(net_sales=('net_sales','sum')).reset_index().sort_values('net_sales',ascending=False)
plt.figure(figsize=(10,4))
plt.bar(by_channel['order_type'],by_channel['net_sales'])
plt.title("Sales by Channel")
plt.xticks(rotation=25,ha='right')
save_fig("sales_by_channel.png")

prod=df.groupby('Product Name').agg(units=('Quantity Sold','sum'),net_sales=('Ext Item Price','sum')).reset_index()
top_rev=prod.sort_values('net_sales',ascending=False).head(10)
top_units=prod.sort_values('units',ascending=False).head(10)

plt.figure(figsize=(10,5))
plt.barh(top_rev['Product Name'][::-1],top_rev['net_sales'][::-1])
plt.title("Top 10 Products by Net Sales")
save_fig("top_products_revenue.png")

plt.figure(figsize=(10,5))
plt.barh(top_units['Product Name'][::-1],top_units['units'][::-1])
plt.title("Top 10 Products by Units")
save_fig("top_products_units.png")

state=orders[orders['pickup']==False].groupby('ship_state').agg(net_sales=('net_sales','sum')).reset_index().sort_values('net_sales',ascending=False).head(10)
plt.figure(figsize=(10,4))
plt.bar(state['ship_state'],state['net_sales'])
plt.title("Top States by Net Sales")
save_fig("top_states.png")

# ---------- KPI Tile ----------
icon_paths={
    "Net Sales":"/mnt/data/Net Sales.png",
    "Total Collected":"/mnt/data/Total Collected.png",
    "Orders":"/mnt/data/Orders.png",
    "Units Sold":"/mnt/data/Units Sold.png",
    "Avg Order Value":"/mnt/data/Avg order value.png",
    "Avg Bottle Price":"/mnt/data/Average Bottle Price.png",
    "Unique Customers":"/mnt/data/Unique Customers.png",
    "Repeat Rate":"/mnt/data/Repeat Rate.png",
    "Avg Bottles / Customer":"/mnt/data/Average bottles Cust.png",
    "Shipped Orders":"/mnt/data/Shipped orders.png",
    "Pickup Orders":"/mnt/data/Pickup orders.png",
    "Taxes Collected":"/mnt/data/Taxes Collected.png",
    "Peak Month":"/mnt/data/Peak Month.png",
    "Lowest Month":"/mnt/data/Lowest month.png",
}

def money0(x): return "${:,.0f}".format(x)
def money2(x): return "${:,.2f}".format(x)
def pct(x): return "{:.1%}".format(x)

class KPITile(Flowable):
    def __init__(self, icon,label,value,w=2.1*inch,h=1.35*inch):
        super().__init__()
        self.icon=icon; self.label=label; self.value=value
        self.width=w; self.height=h
    def draw(self):
        c=self.canv
        c.setFillColor(colors.black)
        c.rect(0,0,self.width,self.height,fill=1,stroke=0)
        try:
            c.drawImage(self.icon,0.12*inch,self.height-0.55*inch,0.35*inch,0.35*inch,mask='auto')
        except:
            pass
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold",14)
        c.drawString(0.12*inch,0.6*inch,str(self.value))
        c.setFont("Helvetica",9)
        c.drawString(0.12*inch,0.32*inch,self.label)

# ---------- PDF ----------
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name="TitleCenter",parent=styles["Title"],alignment=TA_CENTER))

report_path="/mnt/data/GrimmsBluff_2025_Sales_Management_Report_FINAL_v8.pdf"
doc=SimpleDocTemplate(report_path,pagesize=letter,rightMargin=0.6*inch,leftMargin=0.6*inch,topMargin=0.6*inch,bottomMargin=0.6*inch)

story=[]
story.append(Paragraph("2025 Sales Management Report",styles["TitleCenter"]))
story.append(Spacer(1,0.1*inch))

kpis=[
("Net Sales",money0(net_sales)),("Total Collected",money0(order_total)),("Orders",f"{total_orders:,}"),
("Units Sold",f"{int(total_units):,}"),("Avg Order Value",money0(aov)),("Avg Bottle Price",money2(avg_bottle_price)),
("Unique Customers",f"{unique_customers:,}"),("Repeat Rate",pct(repeat_rate)),
("Avg Bottles / Customer",f"{avg_bottles_per_customer:,.1f}"),("Shipped Orders",f"{shipping_count:,}"),
("Pickup Orders",f"{pickup_count:,}"),("Taxes Collected",money0(taxes)),
("Peak Month",f"{peak_row['month'].strftime('%b %Y')} ({money0(peak_row['net_sales'])})"),
("Lowest Month",f"{low_row['month'].strftime('%b %Y')} ({money0(low_row['net_sales'])})")
]

tiles=[KPITile(icon_paths[l],l,v) for l,v in kpis]

grid=[]; row=[]
for i,t in enumerate(tiles,1):
    row.append(t)
    if i%3==0:
        grid.append(row); row=[]
if row:
    while len(row)<3: row.append(Spacer(1,1.35*inch))
    grid.append(row)

story.append(Table(grid,colWidths=[2.15*inch]*3,rowHeights=[1.45*inch]*len(grid)))
story.append(PageBreak())

story.append(Paragraph("Sales Overview",styles["Heading1"]))
story.append(Image(os.path.join(out_dir,"monthly_net_sales.png"),6.8*inch,2.8*inch))
story.append(Spacer(1,0.15*inch))
story.append(Image(os.path.join(out_dir,"monthly_orders_units.png"),6.8*inch,2.8*inch))
story.append(PageBreak())

story.append(Paragraph("Channel Performance",styles["Heading1"]))
story.append(Image(os.path.join(out_dir,"sales_by_channel.png"),6.8*inch,3.0*inch))
story.append(PageBreak())

story.append(Paragraph("Product Performance",styles["Heading1"]))
story.append(Image(os.path.join(out_dir,"top_products_revenue.png"),6.8*inch,3.1*inch))
story.append(Spacer(1,0.15*inch))
story.append(Image(os.path.join(out_dir,"top_products_units.png"),6.8*inch,3.1*inch))
story.append(PageBreak())

story.append(Paragraph("Customer Geography",styles["Heading1"]))
story.append(Image(os.path.join(out_dir,"top_states.png"),6.8*inch,3.0*inch))

doc.build(story)

report_path
