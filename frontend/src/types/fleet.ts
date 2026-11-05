export type Vehicle = {id:string; name?:string; vehicle_type?:string; status?:string; active?:boolean; latitude?:number; longitude?:number; speed?:number; heading?:number|null; timestamp?:string; lastUpdate?:number};
export type Geofence = {id:string;name:string;latitude:number;longitude:number;radius_m:number;active:boolean;demo_seed?:boolean};
export type Alert = {id:string;vehicle_id:string;type:string;message:string;details?:Record<string,any>;timestamp:string};
export type RecoveryPlan = {id:string;delayed_vehicle_id:string;helper_vehicle_id?:string;status:string;radius_km:number;created_at:string;plan?:any};
