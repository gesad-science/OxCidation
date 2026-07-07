#include<stdio.h>
int main(){
  int n,m,h,k,i,j,ans,d[1001],t,r[1001],b,c,min;
  while(scanf("%d %d %d %d",&n,&m,&h,&k),n||m||h||k){
    char a[1001][1001]={0};
    for(i=ans=0;i<n;i++)scanf("%d",&d[i+1]);
    for(i=0;i<m;i++){
      scanf("%d %d",&b,&c);
      a[c][b]=1;
    }
    for(i=h-1;i;i--){
      for(j=1;j<=n;j++){
	if(a[i][j]==0)continue;
	t=d[j];
	d[j]=d[j+1];
	d[j+1]=t;
      }
    }
    for(i=1;i<=n;i++){
      r[i]=i;
      if(i<=k)ans+=d[i];
    }
    min=ans;
    for(i=1;i<h;i++){//printf("%d %d\n",i-1,min);
      for(j=1;j<n;j++){
	if(a[i][j]==0)continue;
	if(r[j]<=k&&r[j+1]>k){
	  if(min>ans-d[j]+d[j+1])min=ans-d[j]+d[j+1];
	}
	else if(r[j+1]<=k&&r[j]>k){
	  if(min>ans-d[j+1]+d[j])min=ans-d[j+1]+d[j];
	}
	t=r[j];
	r[j]=r[j+1];
	r[j+1]=t;
	t=d[j];
	d[j]=d[j+1];
	d[j+1]=t;
      }//printf("%d %d\n",i,min);
    }
    printf("%d\n",min);
  }
  return 0;
}
    
	